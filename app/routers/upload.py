import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from obspy import read, read_inventory
from obspy.clients.fdsn.header import FDSNNoDataException

from app.services.upload_storage import (
    create_session,
    store_stream,
    store_inventory,
    get_stream,
    get_inventory,
    remove_session,
)
from app.services.inventory_service import unique_channels, unique_locations
from app.services.waveform_service import stream_to_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["Upload"])


@router.post("/miniseed")
async def upload_miniseed(file: UploadFile = File(...)):
    """Upload satu file MiniSEED, simpan di Local Upload Storage."""
    logger.info("Upload MiniSEED file=%s", file.filename)
    if not file.filename:
        raise HTTPException(400, "No file provided.")

    try:
        contents = await file.read()
        stream = read(io.BytesIO(contents))
    except Exception:
        raise HTTPException(
            400, "Failed to read MiniSEED file."
        )

    if len(stream) == 0:
        raise HTTPException(
            400, "MiniSEED file contains no traces."
        )

    session_id = create_session()
    store_stream(session_id, stream)

    traces = []
    station = ""

    for trace in stream:
        station = trace.stats.station or station

        traces.append({
            "location": trace.stats.location or "--",
            "channel": trace.stats.channel or "",
            "sampling_rate": trace.stats.sampling_rate,
            "raw_point_count": len(trace.data),
        })

    start_time = str(stream[0].stats.starttime)
    end_time = str(stream[0].stats.endtime)

    return {
        "session_id": session_id,
        "station": station,
        "start_time": start_time,
        "end_time": end_time,
        "traces": traces,
    }


@router.post("/stationxml")
async def upload_stationxml(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """Upload satu file StationXML untuk session yang sudah ada."""
    if not session_id:
        raise HTTPException(400, "session_id is required.")

    from app.services.upload_storage import session_exists
    if not session_exists(session_id):
        raise HTTPException(
            404, "Session not found. Upload MiniSEED first."
        )

    if not file.filename:
        raise HTTPException(400, "No file provided.")

    try:
        contents = await file.read()
        inventory = read_inventory(contents)
    except Exception:
        raise HTTPException(
            400, "Failed to parse StationXML file."
        )

    store_inventory(session_id, inventory)

    return {
        "session_id": session_id,
        "channels": unique_channels(inventory),
        "locations": unique_locations(inventory),
    }


@router.get("/{session_id}/waveform")
def get_upload_waveform(
    session_id: str,
    max_points: int | None = None,
):
    """Ambil waveform display dari session upload.
    Menggunakan stream_to_json() yang sama dengan FDSN —
    termasuk temporal-order decimation.
    """
    stream = get_stream(session_id)
    if stream is None:
        raise HTTPException(
            404, "Upload session not found."
        )

    station = (
        stream[0].stats.station if len(stream) > 0
        else ""
    )
    return stream_to_json(
        stream, station, max_points=max_points,
    )


@router.delete("/{session_id}")
def delete_session(session_id: str):
    """Hapus session upload dan semua data terkait."""
    remove_session(session_id)
    return {"status": "cleared", "session_id": session_id}
