from datetime import datetime

from sqlalchemy.orm import Session
from obspy import Stream, UTCDateTime

from app.services.waveform_service import (
    download_waveform,
    WaveformNoDataError,
)
from app.services.waveform_storage_service import (
    compute_hourly_windows,
    save_waveform_window,
    load_cached_window,
    get_cached_channels_for_window,
    get_seen_channels,
)


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
        # Source of truth: channel yang PERNAH di-cache
        # untuk station ini, BUKAN inventori FDSN station
        # (yang mencatat semua channel metadata, termasuk
        # channel tanpa waveform data seperti VHE/VHN/VHZ).
        # Union dibatasi ke pola channel & location request
        # (mis. `SH*` → hanya SHE/SHN/SHZ), sehingga
        # completeness check wildcard tidak membandingkan
        # terhadap seluruh channel station.
        # Union kosong = station ini belum pernah di-request
        # → skip cache check, langsung download.
        expected_channels = get_seen_channels(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
        )
    else:
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
