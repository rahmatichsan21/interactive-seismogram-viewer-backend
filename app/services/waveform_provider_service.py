from sqlalchemy.orm import Session

from app.services.waveform_service import download_waveform
from app.services.waveform_storage_service import (
    get_cached_waveform,
    save_waveform_stream,
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
    Return waveform from cache if available,
    otherwise download it and cache the result.
    """

    cached_stream = get_cached_waveform(
        db=db,
        network=network,
        station=station,
        location=location,
        channel=channel,
        start_time=start_time,
        end_time=end_time,
    )

    if cached_stream is not None:
        print(
            f"[CACHE HIT] {network}.{station} "
            f"{location}.{channel} "
            f"{start_time} -> {end_time}"
        )
        return cached_stream

    print(
        f"[CACHE MISS] {network}.{station} "
        f"{location}.{channel} "
        f"{start_time} -> {end_time}"
    )

    stream = download_waveform(
        network=network,
        station=station,
        location=location,
        channel=channel,
        start_time=start_time,
        end_time=end_time,
    )

    save_waveform_stream(
        stream=stream,
        db=db,
        requested_start_time=start_time,
        requested_end_time=end_time,
    )

    return stream