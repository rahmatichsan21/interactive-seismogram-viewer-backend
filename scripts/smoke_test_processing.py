from app.services.waveform_service import download_waveform
from app.services.processing_service import apply_pipeline

stream = download_waveform(
    network="IA",
    station="AAFM",
    location="*",
    channel="SHZ",
    start_time="2025-07-01T00:00:00",
    end_time="2025-07-01T00:10:00",
)

operations = [
    {
        "type": "trim",
        "start_time": "2025-07-01T00:02:00",
        "end_time": "2025-07-01T00:04:00",
    }
]

print("Before Trim")
print(stream)
processed = apply_pipeline(
    stream,
    operations,
)
print()

print("After Trim")
print(processed)