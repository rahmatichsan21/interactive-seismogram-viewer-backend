from sqlalchemy.orm import Session

from app.services.waveform_service import download_waveform
from app.services.waveform_storage_service import (
    get_cached_waveform,
    get_cached_channel_set,
    save_waveform_stream,
)
from app.services.inventory_service import get_available_channels


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

    is_wildcard = "*" in channel or "?" in channel

    if is_wildcard:
        expected_channels = set(
            get_available_channels(
                network=network,
                station=station,
                start_time=start_time,
                end_time=end_time,
            )
        )

        cached_channels = get_cached_channel_set(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=start_time,
            end_time=end_time,
        )

        if expected_channels and expected_channels.issubset(
            cached_channels
        ):
            print(
                f"[CACHE HIT] {network}.{station} "
                f"{location}.{channel} "
                f"{start_time} -> {end_time}"
            )
            return get_cached_waveform(
                db=db,
                network=network,
                station=station,
                location=location,
                channel=channel,
                start_time=start_time,
                end_time=end_time,
            )

        print(
            f"[CACHE PARTIAL] {network}.{station} "
            f"{location}.{channel} "
            f"cached={sorted(cached_channels)} "
            f"expected={sorted(expected_channels)}"
        )

    else:
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