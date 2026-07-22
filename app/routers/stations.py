from fastapi import APIRouter

from app.services.station_service import (
    get_all_stations,
    get_station_info,
)

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
    print(">>> station-info called")
    return get_station_info(
        network,
        station,
    )