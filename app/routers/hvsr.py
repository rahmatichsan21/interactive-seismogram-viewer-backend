import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from obspy import UTCDateTime

from app.core.database import get_db
from app.core.config import (
    HVSR_WINDOW_SECONDS,
    HVSR_FMIN,
    HVSR_FMAX,
    HVSR_REJECTION_ENABLED,
)
from app.services.waveform_provider_service import get_waveform
from app.services.waveform_service import WaveformNoDataError
from app.services.hvsr_service import compute_hvsr_result
from app.services.ttl_cache import make_cache_key, hvsr_cache
from app.services.upload_storage import (
    get_stream as get_upload_stream,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["HVSR"])


def _select_trace(stream, network, station, location, channel):
    """Pilih trace yang cocok (channel + network/station/location,
    dengan normalisasi lokasi seperti PSD)."""
    for tr in stream:
        tr_location = tr.stats.location or "--"
        if (
            tr.stats.channel == channel
            and (
                network in ("*", "")
                or (tr.stats.network or "") == network
            )
            and (
                station in ("*", "")
                or (tr.stats.station or "") == station
            )
            and (
                location == "*"
                or tr_location == (location or "--")
            )
        ):
            return tr
    return None


@router.get("/hvsr")
def get_hvsr(
    network: str = None,
    station: str = None,
    location: str = None,
    channel_n: str = None,
    channel_e: str = None,
    channel_z: str = None,
    start_time: str = None,
    end_time: str = None,
    session_id: str = None,
    trim_start: str = None,
    trim_end: str = None,
    db: Session = Depends(get_db),
):
    """
    Hitung HVSR (Nakamura H/V) dari tiga komponen N/E/Z yang sedang
    ditampilkan (channel konkret, bukan wildcard). Menggunakan RAW
    waveform + trim (konsisten dgn PSD/Spectrogram). Output PNG base64.
    """
    try:
        logger.info(
            "HVSR %s.%s [%s, %s, %s] %s -> %s (session=%s)",
            network, station, channel_n, channel_e, channel_z,
            start_time, end_time, session_id,
        )

        if session_id:
            stream = get_upload_stream(session_id)
            if stream is None:
                raise HTTPException(
                    404, "Upload session not found."
                )
            n_trace = _select_trace(
                stream, network, station, location, channel_n
            )
            e_trace = _select_trace(
                stream, network, station, location, channel_e
            )
            z_trace = _select_trace(
                stream, network, station, location, channel_z
            )
        else:
            n_stream = get_waveform(
                db=db,
                network=network,
                station=station,
                location=location,
                channel=channel_n,
                start_time=start_time,
                end_time=end_time,
            )
            e_stream = get_waveform(
                db=db,
                network=network,
                station=station,
                location=location,
                channel=channel_e,
                start_time=start_time,
                end_time=end_time,
            )
            z_stream = get_waveform(
                db=db,
                network=network,
                station=station,
                location=location,
                channel=channel_z,
                start_time=start_time,
                end_time=end_time,
            )
            n_trace = _select_trace(
                n_stream, network, station, location, channel_n
            )
            e_trace = _select_trace(
                e_stream, network, station, location, channel_e
            )
            z_trace = _select_trace(
                z_stream, network, station, location, channel_z
            )

        missing = []
        if n_trace is None:
            missing.append(channel_n)
        if e_trace is None:
            missing.append(channel_e)
        if z_trace is None:
            missing.append(channel_z)
        if missing:
            raise ValueError(
                "Komponen tidak tersedia untuk HVSR: "
                + ", ".join(missing)
            )

        if trim_start and trim_end:
            n_trace = n_trace.copy()
            e_trace = e_trace.copy()
            z_trace = z_trace.copy()
            n_trace.trim(
                UTCDateTime(trim_start), UTCDateTime(trim_end)
            )
            e_trace.trim(
                UTCDateTime(trim_start), UTCDateTime(trim_end)
            )
            z_trace.trim(
                UTCDateTime(trim_start), UTCDateTime(trim_end)
            )

        cache_key = make_cache_key(
            network, station, location,
            channel_n, channel_e, channel_z,
            start_time, end_time, trim_start, trim_end, session_id,
            HVSR_WINDOW_SECONDS, HVSR_FMIN, HVSR_FMAX,
            HVSR_REJECTION_ENABLED,
        )
        cached = hvsr_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "HVSR CACHE HIT %s.%s [%s, %s, %s]",
                network, station, channel_n, channel_e, channel_z,
            )
            return {
                "network": network,
                "station": station,
                "location": location,
                "channels": [channel_n, channel_e, channel_z],
                "hvsr_image": cached["image"],
                "meta": cached["meta"],
            }

        result = compute_hvsr_result(
            n_trace, e_trace, z_trace,
            window_seconds=HVSR_WINDOW_SECONDS,
            fmin=HVSR_FMIN,
            fmax=HVSR_FMAX,
            rejection_enabled=HVSR_REJECTION_ENABLED,
        )
        hvsr_cache.put(cache_key, result)
        logger.info(
            "HVSR CACHE PUT %s.%s [%s, %s, %s]",
            network, station, channel_n, channel_e, channel_z,
        )

        return {
            "network": network,
            "station": station,
            "location": location,
            "channels": [channel_n, channel_e, channel_z],
            "hvsr_image": result["image"],
            "meta": result["meta"],
        }

    except WaveformNoDataError as exc:
        logger.exception(
            "HVSR no data %s.%s [%s, %s, %s]",
            network, station, channel_n, channel_e, channel_z,
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        logger.exception(
            "HVSR invalid %s.%s [%s, %s, %s]",
            network, station, channel_n, channel_e, channel_z,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "HVSR failed %s.%s [%s, %s, %s]",
            network, station, channel_n, channel_e, channel_z,
        )
        raise HTTPException(status_code=500, detail=str(exc))