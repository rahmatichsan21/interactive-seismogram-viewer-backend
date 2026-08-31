import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.download import MiniSeedDownloadRequest
from app.services.miniseed_export_service import (
    apply_export_trim,
    format_filename,
    load_export_stream,
    write_mseed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/download", tags=["Download"])


@router.post("/miniseed")
def download_miniseed(
    request: MiniSeedDownloadRequest,
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            "Download MiniSEED start source=%s stations=%s channels=%s traces=%d",
            request.source,
            request.stations,
            request.channels,
            len(request.traces or []),
        )
        stream = load_export_stream(db, request)
        if len(stream) == 0:
            raise HTTPException(
                404, "No requested raw waveform traces found."
            )

        stream = stream.copy()
        apply_export_trim(
            stream,
            request.trim_start,
            request.trim_end,
        )
        output = write_mseed(stream)
        filename = format_filename(request)
        logger.info("Download MiniSEED done filename=%s", filename)

        def iterate_file():
            try:
                while True:
                    chunk = output.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                output.close()

        return StreamingResponse(
            iterate_file(),
            media_type="application/vnd.fdsn.mseed",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"'
                )
            },
        )
    except HTTPException:
        raise
    except LookupError as error:
        logger.exception(
            "Download MiniSEED not found: %s",
            getattr(request, "source", "unknown"),
        )
        raise HTTPException(404, str(error))
    except ValueError as error:
        logger.exception(
            "Download MiniSEED invalid: %s",
            getattr(request, "source", "unknown"),
        )
        raise HTTPException(400, str(error))
