from app.core.database import SessionLocal
from app.models.waveform import WaveformRecord
from datetime import datetime

db = SessionLocal()

records = (
    db.query(WaveformRecord)
    .filter(
        WaveformRecord.network == "IA",
        WaveformRecord.station == "AAI",
        WaveformRecord.start_time == datetime(2025, 7, 1, 0, 0),
        WaveformRecord.end_time == datetime(2025, 7, 2, 0, 0),
    )
    .all()
)

print(f"Jumlah row di DB untuk window 1 hari ini: {len(records)}")
print()

for r in records:
    print(
        f"  id={r.id} | loc={r.location!r} chan={r.channel!r} "
        f"| created_at={r.created_at} | file={r.file_path}"
    )

db.close()