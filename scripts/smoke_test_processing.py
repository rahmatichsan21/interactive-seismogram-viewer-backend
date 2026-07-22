from app.services.waveform_service import download_waveform
from app.services.processing_service import process_stream

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
        "type": "trim"
    }
]

processed = process_stream(
    stream,
    operations,
)

print(processed)