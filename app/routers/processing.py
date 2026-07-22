from fastapi import APIRouter, HTTPException

from app.models.processing import ProcessRequest
from app.services.processing_service import process_waveform
from app.services.waveform_service import download_waveform, stream_to_json


router = APIRouter(prefix="/process", tags=["Processing"])


@router.post("")
def process(request: ProcessRequest):
    try:
        stream = download_waveform(
            network=request.network,
            station=request.station,
            location=request.location,
            channel=request.channel,
            start_time=request.start_time,
            end_time=request.end_time,
        )

        processed_stream = process_waveform(
            stream=stream,
            operations=[op.model_dump() for op in request.operations],
        )

        return stream_to_json(
            processed_stream,
            request.station,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )