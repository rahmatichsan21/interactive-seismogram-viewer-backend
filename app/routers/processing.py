import logging

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from obspy import Stream, UTCDateTime

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
from app.services.upload_storage import get_inventory as get_upload_inventory
from app.services.persistent_instrument_response_cache import (
    resolve_instrument_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/process", tags=["Processing"])


def _resolve_inventory(request, db):
    """
    Siapkan inventory/response untuk Instrument Correction.
    Local: dari StationXML yang di-upload pada session.
    FDSN:  fetch `level="response"` untuk station/channel request.
    """
    if not any(
        op.type == "instrument_correction"
        for op in request.operations
    ):
        return None

    if request.session_id:
        inventory = get_upload_inventory(request.session_id)
        if inventory is None:
            raise ValueError(
                "StationXML belum di-upload. Upload StationXML "
                "terlebih dahulu sebelum Instrument Correction."
            )
        return inventory

    # FDSN: cache Inventory level="response" per (network, station).
    # Satu StationXML per station (semua channel & epoch); Instrument
    # Correction memilih response via get_response(seed_id, time).
    inventory = resolve_instrument_response(
        request.network,
        request.station,
    )

    if inventory is None:
        raise ValueError(
            f"Response FDSN tidak tersedia untuk "
            f"{request.network}.{request.station}."
        )

    return inventory


@router.post("")
def process(
        request: ProcessRequest,
        db: Session = Depends(get_db),
    ):
    try:
        logger.info(
            "Process %s.%s %s (%s -> %s) ops=%s",
            request.network, request.station,
            request.channel, request.start_time, request.end_time,
            [op.type for op in request.operations],
        )
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

        # Context untuk operation handler. Instrument Correction
        # membutuhkan inventory/response — di-resolve di sini
        # (Local session StationXML vs FDSN level="response").
        context = {
            "inventory": _resolve_inventory(request, db),
        }

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
            context=context,
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
        logger.exception(
            "Processing no data %s.%s (%s -> %s)",
            request.network, request.station,
            request.start_time, request.end_time,
        )
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        # Termasuk kegagalan validasi per-channel (mis. Nyquist
        # gagal di satu channel) - technical debt yang sudah kita
        # sepakati: kalau satu channel gagal, SELURUH request ini
        # gagal (all-or-nothing), belum partial-per-channel.
        logger.exception(
            "Processing invalid %s.%s (%s -> %s): %s",
            request.network, request.station,
            request.start_time, request.end_time, exc,
        )
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        logger.exception(
            "Processing failed %s.%s (%s -> %s): %s",
            request.network, request.station,
            request.start_time, request.end_time, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )