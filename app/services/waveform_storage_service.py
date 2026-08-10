from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.waveform import WaveformRecord
from app.core.config import BASE_DIR, CACHE_WINDOW_SECONDS
from obspy import Stream, read


STORAGE_DIR = BASE_DIR / "storage" / "waveforms"


def compute_hourly_windows(request_start: datetime, request_end: datetime):
    """
    Pecah rentang request user menjadi jendela UTC-aligned
    selebar CACHE_WINDOW_SECONDS.

    Contoh:
      08:45 → 10:45  dengan CACHE_WINDOW_SECONDS=3600
      menghasilkan:  [08:00-09:00, 09:00-10:00, 10:00-11:00]
    """
    seconds_since_midnight = (
        request_start.hour * 3600
        + request_start.minute * 60
        + request_start.second
    )
    floored = (
        seconds_since_midnight // CACHE_WINDOW_SECONDS
    ) * CACHE_WINDOW_SECONDS
    current = request_start.replace(
        hour=floored // 3600,
        minute=(floored % 3600) // 60,
        second=0,
        microsecond=0,
    )

    windows = []
    while current < request_end:
        window_end = current + timedelta(
            seconds=CACHE_WINDOW_SECONDS
        )
        windows.append((current, window_end))
        current = window_end
    return windows


def save_waveform_window(
    stream,
    db: Session,
    window_start: datetime,
    window_end: datetime,
):
    """
    Simpan SEMUA trace dalam stream sebagai record untuk
    SATU jendela cache (satu jam UTC-aligned).

    Setiap trace mendapatkan satu record DB dengan
    start_time=window_start, end_time=window_end.
    File MiniSEED disimpan di STORAGE_DIR.

    Cek-before-insert: kalau record sudah ada, file ditimpa
    tapi DB row tidak di-duplikasi.
    """
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    for trace in stream:
        network = trace.stats.network or ""
        station = trace.stats.station or ""
        location = trace.stats.location or ""
        channel = trace.stats.channel or ""
        safe_location = location or "--"

        filename = (
            f"{network}.{station}."
            f"{safe_location}.{channel}."
            f"{window_start.strftime('%Y%m%dT%H%M%S')}."
            f"{window_end.strftime('%Y%m%dT%H%M%S')}"
            f".mseed"
        )
        file_path = STORAGE_DIR / filename

        existing = (
            db.query(WaveformRecord)
            .filter(
                WaveformRecord.network == network,
                WaveformRecord.station == station,
                WaveformRecord.location == location,
                WaveformRecord.channel == channel,
                WaveformRecord.start_time == window_start,
                WaveformRecord.end_time == window_end,
            )
            .first()
        )

        trace.write(str(file_path), format="MSEED")

        if existing is not None:
            continue

        record = WaveformRecord(
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=window_start,
            end_time=window_end,
            file_path=str(file_path),
        )
        db.add(record)

    db.commit()


def load_cached_window(
    db: Session,
    network: str,
    station: str,
    location: str,
    channel: str,
    window_start: datetime,
    window_end: datetime,
):
    """
    Muat SEMUA trace yang sudah di-cache untuk SATU jendela.
    Wildcard-aware: channel menjadi SQL LIKE pattern.
    """
    location_pattern = location.replace("*", "%")
    channel_pattern = channel.replace("*", "%")

    records = (
        db.query(WaveformRecord)
        .filter(
            WaveformRecord.network == network,
            WaveformRecord.station == station,
            WaveformRecord.location.like(location_pattern),
            WaveformRecord.channel.like(channel_pattern),
            WaveformRecord.start_time == window_start,
            WaveformRecord.end_time == window_end,
        )
        .all()
    )

    stream = Stream()
    for record in records:
        file_path = Path(record.file_path)
        if not file_path.exists():
            continue
        stream += read(str(file_path))
    return stream


def get_cached_channels_for_window(
    db: Session,
    network: str,
    station: str,
    location: str,
    channel: str,
    window_start: datetime,
    window_end: datetime,
):
    """
    Kembalikan set channel code yang SUDAH di-cache
    untuk SATU jendela. Dipakai provider untuk mengecek
    kelengkapan per-jendela sebelum cache hit.
    """
    location_pattern = location.replace("*", "%")
    channel_pattern = channel.replace("*", "%")

    rows = (
        db.query(WaveformRecord.channel)
        .filter(
            WaveformRecord.network == network,
            WaveformRecord.station == station,
            WaveformRecord.location.like(location_pattern),
            WaveformRecord.channel.like(channel_pattern),
            WaveformRecord.start_time == window_start,
            WaveformRecord.end_time == window_end,
        )
        .distinct()
        .all()
    )

    return {row[0] for row in rows}


def get_seen_channels(
    db: Session,
    network: str,
    station: str,
):
    """
    Kembalikan UNION semua channel code yang PERNAH
    di-cache untuk station ini — lintas jendela waktu,
    lintas location. Source of truth untuk menentukan
    channel mana yang benar-benar deliverable oleh FDSN
    waveform server untuk station ini.

    Kalau kosong, berarti belum pernah ada request untuk
    station ini — provider akan skip cache check dan
    langsung download.
    """
    rows = (
        db.query(WaveformRecord.channel)
        .filter(
            WaveformRecord.network == network,
            WaveformRecord.station == station,
        )
        .distinct()
        .all()
    )

    return {row[0] for row in rows}


def get_all_waveform_records_older_than(
    db: Session,
    cutoff: datetime,
):
    """
    Ambil semua record cache yang created_at-nya lebih
    tua dari `cutoff`. Dipakai oleh cleanup_cache.py.
    """
    return (
        db.query(WaveformRecord)
        .filter(WaveformRecord.created_at < cutoff)
        .all()
    )
