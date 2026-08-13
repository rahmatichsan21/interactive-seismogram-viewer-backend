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

router = APIRouter(prefix="/api/download", tags=["Download"])


@router.post("/miniseed")
def download_miniseed(
    request: MiniSeedDownloadRequest,
    db: Session = Depends(get_db),
):
    try:
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
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(400, str(error))
