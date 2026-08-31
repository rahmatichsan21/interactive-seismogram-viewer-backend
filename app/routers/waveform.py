import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
from app.services.persistent_instrument_response_cache import (
    preload_instrument_response,
)
from sqlalchemy.orm import Session

from app.core.database import get_db

logger = logging.getLogger(__name__)



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
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            "Load waveform %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        stream = get_waveform(
            db=db,
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=start_time,
            end_time=end_time,
        )

        # Preload Instrument Response (per station) di background agar
        # Instrument Correction berikutnya tidak menunggu FDSN. Best-effort:
        # kegagalan tidak memengaruhi response waveform.
        if background_tasks is not None:
            background_tasks.add_task(
                preload_instrument_response,
                network,
                station,
            )

        return stream_to_json(
            stream=stream,
            station=station,
            max_points=max_points,
        )

    except WaveformNoDataError as error:
        logger.exception(
            "Waveform no data %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )

    except ValueError as error:
        logger.exception(
            "Invalid waveform request %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
    except Exception as error:
        logger.exception(
            "Failed to load waveform %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
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