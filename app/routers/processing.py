from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.processing import ProcessRequest
from app.services.processing_service import (
    process_waveform_per_channel,
)
from app.services.waveform_service import (
    trace_to_json,
    WaveformNoDataError,
)

from app.services.waveform_provider_service import (
    get_waveform,
)
from app.services.upload_storage import get_stream as get_upload_stream

router = APIRouter(prefix="/process", tags=["Processing"])


@router.post("")
def process(
        request: ProcessRequest,
        db: Session = Depends(get_db),
    ):
    try:
        if request.session_id:
            stream = get_upload_stream(request.session_id)
            if stream is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Upload session not found. "
                        "The session may have expired or "
                        "been cleared. Please re-upload "
                        "the MiniSEED file."
                    ),
                )
        else:
            stream = get_waveform(
                db=db,
                network=request.network,
                station=request.station,
                location=request.location,
                channel=request.channel,
                start_time=request.start_time,
                end_time=request.end_time,
            )

        response_traces = []

        # Cache info untuk ProcessingCache — dipakai oleh
        # pipeline untuk membuat snapshot SEBELUM operation mahal
        # dan oleh generator untuk cek cache hit.
        cache_info = {
            "network": request.network,
            "station": request.station,
            "start_time": request.start_time,
            "end_time": request.end_time,
        }

        # Sequential Per-Channel: process_waveform_per_channel()
        # adalah generator - tiap iterasi cuma SATU channel yang
        # "in flight" di memori. trace_to_json() (serialize +
        # Time Bucket decimation) dipanggil SEGERA per channel,
        # sebelum generator lanjut ke channel berikutnya dan
        # melepas referensi channel ini (lihat
        # processing_service.py). Decimation berjalan di sini,
        # PALING AKHIR - SETELAH seluruh operasi pada channel ini
        # selesai diproses.
        for processed_trace in process_waveform_per_channel(
            stream=stream,
            operations=request.operations,
            cache_info=cache_info,
        ):
            response_traces.append(
                trace_to_json(
                    processed_trace,
                    request.max_points,
                )
            )

        return {
            "station": request.station,
            "traces": response_traces,
        }

    except WaveformNoDataError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        # Termasuk kegagalan validasi per-channel (mis. Nyquist
        # gagal di satu channel) - technical debt yang sudah kita
        # sepakati: kalau satu channel gagal, SELURUH request ini
        # gagal (all-or-nothing), belum partial-per-channel.
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )