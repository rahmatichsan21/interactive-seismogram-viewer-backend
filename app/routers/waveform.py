from fastapi import APIRouter, Depends, HTTPException
from obspy.clients.fdsn.header import FDSNNoDataException

from app.services.waveform_service import (
    download_waveform,
    stream_to_json,
    WaveformNoDataError,
    get_available_channels,
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
        # 1. Cek cache
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

        # 2. Cache tidak ditemukan
        print(
            f"[CACHE MISS] {network}.{station} "
            f"{location}.{channel} "
            f"{start_time} -> {end_time}"
        )

        # 3. Download waveform
        stream = download_waveform(
            network=network,
            station=station,
            location=location,
            channel=channel,
            start_time=start_time,
            end_time=end_time,
        )

        # 4. Simpan hasil download ke cache/database
        save_waveform_stream(
            stream=stream,
            db=db,
            requested_start_time=start_time,
            requested_end_time=end_time,
        )

        # 5. Kirim ke frontend
        return stream_to_json(
            stream=stream,
            station=station,
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