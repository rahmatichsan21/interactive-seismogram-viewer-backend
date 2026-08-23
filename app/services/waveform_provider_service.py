from datetime import datetime

from sqlalchemy.orm import Session
from obspy import Stream, UTCDateTime
from obspy.clients.fdsn.header import FDSNNoDataException

from app.services.inventory_service import (
    get_inventory as get_fdsn_inventory,
)
from app.services.waveform_service import (
    download_waveform,
    WaveformNoDataError,
)
from app.services.waveform_storage_service import (
    compute_hourly_windows,
    save_waveform_window,
    load_cached_window,
    get_cached_channels_for_window,
)


def _expand_channel_wildcard(
    db,
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    """
    Kembalikan daftar channel KONKRET untuk channel wildcard,
    berdasarkan inventory station (level="channel"), difilter pola.

    "*"   → semua channel konkret yang tersedia pada station.
    "SH*" → channel yang berawalan "SH".
    "S*"  → channel yang berawalan "S".

    Inventory menentukan channel apa yang TERSEDIA; cache hanya
    menjawab data apa yang sudah kita punya. Wildcard tidak pernah
    disimpan sebagai channel — hanya daftar channel konkret yang
    diproses lebih lanjut.
    """
    prefix = channel.replace("*", "").replace("?", "")

    try:
        inventory = get_fdsn_inventory(
            network=network,
            station=station,
            location="*",
            channel="*",
            starttime=UTCDateTime(start_time),
            endtime=UTCDateTime(end_time),
            level="channel",
        )
    except FDSNNoDataException:
        raise WaveformNoDataError(
            f"No channel available for {network}.{station}"
        )

    if not inventory or len(inventory) == 0:
        raise WaveformNoDataError(
            f"No channel available for {network}.{station}"
        )

    channels = []

    for net in inventory:
        for sta in net:
            for ch in sta:
                code = ch.code or ""
                if prefix and not code.startswith(prefix):
                    continue
                if code not in channels:
                    channels.append(code)

    channels.sort()

    if not channels:
        raise WaveformNoDataError(
            f"No channel matches pattern '{channel}' "
            f"for {network}.{station}"
        )

    return channels


def get_waveform(
    db: Session,
    network: str,
    station: str,
    location: str,
    channel: str,
    start_time: str,
    end_time: str,
):
    """
    Return waveform — cek cache per jendela UTC-aligned,
    download hanya jendela yang hilang, assemble, merge,
    trim ke rentang request user.
    """
    request_start = datetime.fromisoformat(start_time)
    request_end = datetime.fromisoformat(end_time)
    windows = compute_hourly_windows(request_start, request_end)

    is_wildcard = "*" in channel or "?" in channel

    if is_wildcard:
        # Wildcard adalah SYNTAX selection, BUKAN channel nyata.
        # Expansion berbasis inventory station → daftar channel
        # konkret yang tersedia. Setiap channel konkret diproses
        # lewat jalur cache/download existing (rekursif, non-wildcard).
        # Cache/database hanya menyimpan channel konkret.
        channels = _expand_channel_wildcard(
            db, network, station, location, channel,
            start_time, end_time,
        )

        combined = Stream()

        for concrete_channel in channels:
            try:
                combined += get_waveform(
                    db=db,
                    network=network,
                    station=station,
                    location=location,
                    channel=concrete_channel,
                    start_time=start_time,
                    end_time=end_time,
                )
            except WaveformNoDataError:
                # Partial: channel ini tidak punya data pada rentang
                # waktu tsb — jangan menggagalkan seluruh request.
                print(
                    f"[WILDCARD PARTIAL] {network}.{station} "
                    f"{location}.{concrete_channel} tidak ada data"
                )
                continue

        if len(combined) == 0:
            raise WaveformNoDataError(
                f"No waveform data found for "
                f"{network}.{station}.{location}.{channel} "
                f"in {start_time} -> {end_time}"
            )

        return combined

    expected_channels = {channel}

    # Cek kelengkapan: setiap jendela punya semua channel?
    all_windows_complete = bool(expected_channels)
    for win_start, win_end in windows:
        cached = get_cached_channels_for_window(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            window_start=win_start,
            window_end=win_end,
        )
        if not expected_channels.issubset(cached):
            all_windows_complete = False
            break

    if all_windows_complete:
        print(
            f"[CACHE HIT] {network}.{station} "
            f"{location}.{channel} "
            f"{start_time} -> {end_time}"
        )
        return _assemble_or_raise(
            db, network, station, location, channel,
            windows, start_time, end_time,
        )

    # Download jendela yang belum lengkap
    any_window_failed = False
    for win_start, win_end in windows:
        cached = get_cached_channels_for_window(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            window_start=win_start,
            window_end=win_end,
        )

        if expected_channels and expected_channels.issubset(
            cached
        ):
            continue

        print(
            f"[DOWNLOAD WINDOW] {network}.{station} "
            f"{location}.{channel} "
            f"{win_start.isoformat()} -> {win_end.isoformat()}"
        )

        try:
            win_stream = download_waveform(
                network=network,
                station=station,
                location=location,
                channel=channel,
                start_time=win_start.isoformat(),
                end_time=win_end.isoformat(),
            )
        except WaveformNoDataError as exc:
            any_window_failed = True
            print(
                f"[DOWNLOAD WINDOW FAILED] {network}.{station} "
                f"{location}.{channel} "
                f"{win_start.isoformat()} -> {win_end.isoformat()} "
                f"reason=WaveformNoDataError: {exc}"
            )
            continue
        except Exception as exc:
            any_window_failed = True
            print(
                f"[DOWNLOAD WINDOW FAILED] {network}.{station} "
                f"{location}.{channel} "
                f"{win_start.isoformat()} -> {win_end.isoformat()} "
                f"reason={type(exc).__name__}: {exc}"
            )
            continue

        save_waveform_window(
            stream=win_stream,
            db=db,
            window_start=win_start,
            window_end=win_end,
        )

    result = _assemble_or_raise(
        db, network, station, location, channel,
        windows, start_time, end_time,
    )

    if any_window_failed:
        print(
            f"[DOWNLOAD PARTIAL] {network}.{station} "
            f"{location}.{channel} — beberapa window gagal "
            f"tetapi ada data yang bisa dikembalikan"
        )

    return result


def _assemble_or_raise(
    db,
    network,
    station,
    location,
    channel,
    windows,
    request_start,
    request_end,
):
    """
    Gabung semua window yang tersedia. Jika hasil akhir kosong
    (tidak ada cache yang valid dan tidak ada download yang
    berhasil), raise WaveformNoDataError agar router dapat
    menghasilkan 404, BUKAN HTTP 200 dengan traces kosong.
    """
    stream = _assemble_and_trim(
        db, network, station, location, channel,
        windows, request_start, request_end,
    )

    if len(stream) == 0:
        raise WaveformNoDataError(
            f"No waveform data found for "
            f"{network}.{station}.{location}.{channel} "
            f"in {request_start} -> {request_end}"
        )

    return stream


def _assemble_and_trim(
    db,
    network,
    station,
    location,
    channel,
    windows,
    request_start,
    request_end,
):
    """Gabung semua jendela, merge, trim ke rentang user."""
    full_stream = Stream()
    for win_start, win_end in windows:
        win_stream = load_cached_window(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            window_start=win_start,
            window_end=win_end,
        )
        full_stream += win_stream

    full_stream.merge(method=1)
    full_stream.trim(
        UTCDateTime(request_start),
        UTCDateTime(request_end),
    )
    return full_stream
