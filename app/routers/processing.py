from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.processing import ProcessRequest
from app.services.processing_service import process_waveform
from app.services.waveform_service import (
    stream_to_json,
)

from app.services.waveform_provider_service import (
    get_waveform,
)

router = APIRouter(prefix="/process", tags=["Processing"])


@router.post("")
def process(
        request: ProcessRequest,
        db: Session = Depends(get_db),
    ):
    try:
        stream = get_waveform(
            db=db,
            network=request.network,
            station=request.station,
            location=request.location,
            channel=request.channel,
            start_time=request.start_time,
            end_time=request.end_time,
        )

        processed_stream = process_waveform(
            stream=stream,
            operations=request.operations,
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