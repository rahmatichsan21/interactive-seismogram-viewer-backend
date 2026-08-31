import logging

from fastapi import APIRouter, HTTPException

from app.services.station_service import (
    get_all_stations,
    get_station_info,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Stations"]
)


@router.get("/stations")
def get_stations():
    return get_all_stations()

@router.get("/station-info")
def station_info(
    network: str,
    station: str,
):
    logger.info("Station info %s.%s", network, station)
    try:
        return get_station_info(
            network,
            station,
        )
    except Exception as exc:
        logger.exception("Station info failed %s.%s", network, station)
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )