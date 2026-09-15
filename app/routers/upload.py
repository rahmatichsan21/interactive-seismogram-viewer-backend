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
    get_stationxml_filenames,
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
    stations = set()

    for trace in stream:
        if trace.stats.station:
            stations.add(trace.stats.station)

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
        # `station` dipertahankan untuk kompatibilitas response lama;
        # `stations` adalah sumber kebenaran untuk local multi-station.
        "station": sorted(stations)[0] if stations else "",
        "stations": sorted(stations),
        "start_time": start_time,
        "end_time": end_time,
        "traces": traces,
    }


@router.post("/stationxml")
async def upload_stationxml(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """Tambah satu StationXML ke kumpulan inventory session upload."""
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

    store_inventory(session_id, inventory, file.filename)

    return {
        "session_id": session_id,
        "filename": file.filename,
        "filenames": get_stationxml_filenames(session_id),
        "channels": unique_channels(inventory),
        "locations": unique_locations(inventory),
    }


@router.get("/stationxml/{session_id}/validation")
def validate_stationxml(session_id: str):
    """Validasi response StationXML untuk seluruh trace local upload.

    Pencocokan dilakukan dengan seed id dan waktu trace yang sama seperti
    Instrument Correction. Hasilnya digabung per station agar frontend
    dapat menjelaskan station mana yang belum memiliki response cocok.
    """
    stream = get_stream(session_id)
    if stream is None:
        raise HTTPException(404, "Upload session tidak ditemukan.")

    inventory = get_inventory(session_id)
    filenames = get_stationxml_filenames(session_id)

    if inventory is None:
        stations = sorted({
            trace.stats.station or "(tanpa kode station)"
            for trace in stream
        })
        return {
            "filenames": [],
            "invalid_stations": [
                {"station": station}
                for station in stations
            ],
        }

    invalid_stations: dict[str, None] = {}

    for trace in stream:
        station = trace.stats.station or "(tanpa kode station)"

        try:
            response = inventory.get_response(
                trace.id,
                trace.stats.starttime,
            )
            stages = response.response_stages or []
            sensitivity = response.instrument_sensitivity

            if (
                not stages
                or sensitivity is None
                or sensitivity.value is None
                or sensitivity.value == 0
            ):
                invalid_stations[station] = None
        except Exception:
            invalid_stations[station] = None

    return {
        "filenames": filenames,
        "invalid_stations": [
            {"station": station}
            for station in sorted(invalid_stations)
        ],
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

    # Sama seperti FDSN (lihat
    # waveform_provider_service._assemble_and_trim): gabung per channel
    # dan pertahankan gap sebagai masked trace, supaya satu channel
    # SELALU tampil sebagai satu trace/viewer, bukan satu trace terpisah
    # per segmen kontinu. obspy.read() pada file MiniSEED yang punya gap
    # nyata mengembalikan beberapa Trace terpisah untuk channel yang
    # sama; tanpa merge ini, stream_to_json() menyerialisasikan tiap
    # segmen sebagai trace JSON sendiri-sendiri, dan frontend merender
    # satu viewer per trace. Merge dilakukan pada SALINAN stream — sesi
    # upload yang tersimpan (dipakai processing/validation/export) tetap
    # stream asli, tidak berubah.
    display_stream = stream.copy()
    display_stream.merge(method=1, fill_value=None)

    station = (
        display_stream[0].stats.station
        if len(display_stream) > 0
        else ""
    )
    return stream_to_json(
        display_stream, station, max_points=max_points,
    )


@router.delete("/{session_id}")
def delete_session(session_id: str):
    """Hapus session upload dan semua data terkait."""
    remove_session(session_id)
    return {"status": "cleared", "session_id": session_id}