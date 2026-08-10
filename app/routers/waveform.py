from fastapi import APIRouter, Depends, HTTPException
from obspy.clients.fdsn.header import FDSNNoDataException

from app.services.inventory_service import (
    get_available_channels,
)
from app.services.waveform_service import (
    stream_to_json,
    WaveformNoDataError,
)

from app.services.waveform_provider_service import (
    get_waveform,
)
from sqlalchemy.orm import Session

from app.core.database import get_db



router = APIRouter(
    prefix="/api",
    tags=["Waveform"]
)


@router.get("/waveform")
def get_waveform_endpoint(
    network: str,
    station: str,
    location: str,
    channel: str,
    start_time: str,
    end_time: str,
    max_points: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        stream = get_waveform(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=start_time,
            end_time=end_time,
        )

        return stream_to_json(
            stream=stream,
            station=station,
            max_points=max_points,
        )

    except WaveformNoDataError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )

@router.get("/channels")
def get_channels(
    network: str,
    station: str,
    start_time: str,
    end_time: str,
):
    try:
        channels = get_available_channels(
            network=network,
            station=station,
            start_time=start_time,
            end_time=end_time,
        )

        return {
            "channels": channels
        }

    except FDSNNoDataException:
        return {
            "channels": []
        }