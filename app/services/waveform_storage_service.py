from pathlib import Path

from sqlalchemy.orm import Session

from app.models.waveform import WaveformRecord
from app.core.config import BASE_DIR
from datetime import datetime

from obspy import Stream, read


# Absolute path (bukan relatif ke CWD) supaya MiniSEED cache
# selalu ditulis ke lokasi yang sama terlepas dari direktori
# kerja saat server/script dijalankan. Relatif ke CWD sebelumnya
# bisa membuat file tersimpan di tempat yang salah sementara DB
# tetap mencatat path-nya - korupsi cache yang diam-diam.
STORAGE_DIR = BASE_DIR / "storage" / "waveforms"


def save_waveform_stream(
    stream,
    db: Session,
    requested_start_time: str,
    requested_end_time: str,
):
    STORAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    saved_records = []
    request_start = datetime.fromisoformat(
        requested_start_time
    )

    request_end = datetime.fromisoformat(
        requested_end_time
    )

    for trace in stream:
        network = trace.stats.network or ""
        station = trace.stats.station or ""
        location = trace.stats.location or ""
        channel = trace.stats.channel or ""

        start_time = trace.stats.starttime
        end_time = trace.stats.endtime

        safe_location = location or "--"

        filename = (
            f"{network}.{station}."
            f"{safe_location}.{channel}."
            f"{start_time.strftime('%Y%m%dT%H%M%S')}."
            f"{end_time.strftime('%Y%m%dT%H%M%S')}"
            f".mseed"
        )

        file_path = STORAGE_DIR / filename

        # Cek-before-insert: kalau record untuk window yang sama
        # sudah ada (dukungan unique constraint
        # uq_waveform_records_cache_key), tulis file-nya ulang
        # TAPI jangan buat baris dobel - langsung lanjut ke
        # record berikutnya.
        existing = (
            db.query(WaveformRecord)
            .filter(
                WaveformRecord.network == network,
                WaveformRecord.station == station,
                WaveformRecord.location == location,
                WaveformRecord.channel == channel,
                WaveformRecord.start_time == request_start,
                WaveformRecord.end_time == request_end,
            )
            .first()
        )

        if existing is not None:
            trace.write(
                str(file_path),
                format="MSEED",
            )
            continue

        # Simpan satu trace sebagai MiniSEED
        trace.write(
            str(file_path),
            format="MSEED",
        )

        record = WaveformRecord(
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=request_start,
            end_time=request_end,
            file_path=str(file_path),
        )

        db.add(record)
        saved_records.append(record)

    db.commit()

    for record in saved_records:
        db.refresh(record)

    return saved_records

def get_cached_waveform(
    db: Session,
    network: str,
    station: str,
    location: str,
    channel: str,
    start_time: str,
    end_time: str,
):
    start_datetime = datetime.fromisoformat(start_time)
    end_datetime = datetime.fromisoformat(end_time)

    # Ubah wildcard FDSN menjadi wildcard SQL
    location_pattern = location.replace("*", "%")
    channel_pattern = channel.replace("*", "%")

    records = (
        db.query(WaveformRecord)
        .filter(
            WaveformRecord.network == network,
            WaveformRecord.station == station,
            WaveformRecord.location.like(location_pattern),
            WaveformRecord.channel.like(channel_pattern),
            WaveformRecord.start_time == start_datetime,
            WaveformRecord.end_time == end_datetime,
        )
        .all()
    )

    if not records:
        return None

    stream = Stream()

    for record in records:
        file_path = Path(record.file_path)

        # Database ada, tetapi file sudah hilang
        if not file_path.exists():
            return None

        stream += read(str(file_path))

    return stream