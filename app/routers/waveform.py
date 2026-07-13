from fastapi import APIRouter
from fastapi.responses import JSONResponse
from obspy.clients.fdsn.header import FDSNNoDataException
from obspy import UTCDateTime

from app.services.waveform_service import (
    client,
    download_waveform,
    stream_to_json,
)
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.waveform_storage_service import (
    get_cached_waveform,
    save_waveform_stream,
)


router = APIRouter(
    prefix="/api",
    tags=["Waveform"]
)


@router.get("/waveform")
def get_waveform(
    network: str,
    station: str,
    location: str,
    channel: str,
    start_time: str,
    end_time: str,
    db: Session = Depends(get_db),
):
    try:
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

            return stream_to_json(
                cached_stream,
                station,
            )

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

    except FDSNNoDataException:
        return JSONResponse(
            status_code=404,
            content={
                "message": "No waveform available."
            },
        )

    return stream_to_json(
        stream=stream,
        station=station,
    )

@router.get("/channels")
def get_channels(
    network: str,
    station: str,
    start_time: str,
    end_time: str,
):
    try:
        inventory = client.get_stations(
            network=network,
            station=station,
            location="*",
            channel="*",
            starttime=UTCDateTime(start_time),
            endtime=UTCDateTime(end_time),
            level="channel",
        )

        channels = sorted({
            channel.code
            for network_item in inventory
            for station_item in network_item
            for channel in station_item
        })

        return {
            "channels": channels
        }

    except FDSNNoDataException:
        return {
            "channels": []
        }