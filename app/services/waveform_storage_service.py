import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.waveform import WaveformRecord
from app.core.config import (
    BASE_DIR,
    CACHE_WINDOW_SECONDS,
)
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
    location: str = "*",
    channel: str = "*",
):
    """
    Kembalikan UNION channel code yang PERNAH di-cache
    untuk station ini — lintas jendela waktu.

    `location` dan `channel` menjadi pola filter (wildcard-aware,
    sama seperti lookup lainnya): hasilnya dibatasi hanya pada
    channel yang sesuai dengan pola request. Ini penting untuk
    completeness check wildcard — mis. request `SH*` hanya boleh
    mengecek kelengkapan SHE/SHN/SHZ, BUKAN seluruh channel yang
    pernah ada di station.

    Kalau kosong, berarti belum pernah ada request untuk
    station ini — provider akan skip cache check dan
    langsung download.
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
        )
        .distinct()
        .all()
    )

    return {row[0] for row in rows}


def run_waveform_cache_cleanup():
    """
    Hapus SELURUH Hourly Waveform Cache: semua file MiniSEED
    di STORAGE_DIR (kecuali marker .last_cleanup) dan semua
    baris WaveformRecord, lalu commit DB.

    Tidak ada lagi retention / created_at cutoff — konsep umur
    file sudah dihapus. Cache dibersihkan menyeluruh setiap hari
    pada waktu HOURLY_CACHE_CLEAR_TIME.

    Reusable — dipanggil oleh scripts/cleanup_cache.py (manual)
    dan background task otomatis di app/main.py. Mengelola
    session DB sendiri.

    Seluruh isi folder STORAGE_DIR adalah Hourly Waveform Cache,
    jadi orphan file (.mseed tanpa DB record) tetap dihapus.
    DB record tanpa file fisik juga tetap dihapus — file dan DB
    dibersihkan sebagai satu lifecycle.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    deleted_files = 0
    deleted_rows = 0

    try:
        # 1. Hapus semua file cache di folder Hourly Waveform.
        #    Marker .last_cleanup TIDAK dihapus oleh cleanup.
        if STORAGE_DIR.exists():
            for entry in STORAGE_DIR.iterdir():
                if (
                    entry.is_file()
                    and entry.name != ".last_cleanup"
                ):
                    try:
                        entry.unlink()
                        deleted_files += 1
                    except Exception as exc:
                        print(
                            f"[CACHE CLEANUP] Gagal hapus file "
                            f"{entry}: {exc}"
                        )

        # 2. Hapus semua DB record (termasuk yang file-nya
        #    sudah hilang). Commit setelah seluruh record
        #    dihapus supaya file & DB bersih bersamaan.
        records = db.query(WaveformRecord).all()
        for record in records:
            db.delete(record)
        db.commit()
        deleted_rows = len(records)

        return deleted_files, deleted_rows
    finally:
        db.close()


def get_last_cleanup_date():
    """
    Baca tanggal terakhir cleanup sukses dari marker file
    (storage/waveforms/.last_cleanup). None jika belum pernah.
    """
    marker = STORAGE_DIR / ".last_cleanup"

    if not marker.exists():
        return None

    try:
        text = marker.read_text().strip()
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return None


def set_last_cleanup_date(date=None):
    """
    Tulis tanggal cleanup terakhir ke marker file.
    Dipanggil SETELAH cleanup berhasil, supaya catch-up
    tidak berulang pada hari yang sama.
    """
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    marker = STORAGE_DIR / ".last_cleanup"

    if date is None:
        date = datetime.now()

    marker.write_text(date.strftime("%Y-%m-%d"))
