import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from obspy import UTCDateTime

from app.core.database import get_db
from app.core.config import PPSD_LENGTH_SECONDS, PPSD_OVERLAP
from app.services.waveform_provider_service import get_waveform
from app.services.waveform_service import WaveformNoDataError
from app.services.persistent_instrument_response_cache import (
    resolve_instrument_response,
)
from app.services.psd_service import compute_psd_image
from app.services.ttl_cache import make_cache_key, psd_cache
from app.services.upload_storage import (
    get_stream as get_upload_stream,
    get_inventory as get_upload_inventory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["PSD"])


@router.get("/psd")
def get_psd(
    channel: str,
    network: Optional[str] = Query(default=None),
    station: Optional[str] = Query(default=None),
    location: Optional[str] = Query(default=None),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    trim_start: Optional[str] = Query(default=None),
    trim_end: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Hitung Power Spectral Density (ObsPy PPSD) untuk satu trace.

    - Waveform dari cache existing (get_waveform / session upload).
    - Instrument response dari StationXML/Inventory yang sudah di-cache.
    - Output PNG base64 (mekanisme image seperti spectrogram).
    """
    try:
        logger.info(
            "PSD %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )

        if session_id:
            stream = get_upload_stream(session_id)
            if stream is None:
                raise HTTPException(
                    404, "Upload session not found."
                )
            inventory = get_upload_inventory(session_id)
            if inventory is None:
                raise ValueError(
                    "StationXML belum di-upload untuk PSD."
                )
        else:
            stream = get_waveform(
                db=db,
                network=network,
                station=station,
                location=location,
                channel=channel,
                start_time=start_time,
                end_time=end_time,
            )
            inventory = resolve_instrument_response(
                network, station
            )

        if inventory is None:
            raise ValueError(
                "Instrument response tidak tersedia untuk PSD."
            )

        trace = None
        for tr in stream:
            tr_location = tr.stats.location or "--"
            if (
                tr.stats.channel == channel
                and (
                    network in ("*", "", None)
                    or (tr.stats.network or "") == network
                )
                and (
                    station in ("*", "", None)
                    or (tr.stats.station or "") == station
                )
                and (
                    location in ("*", None)
                    or tr_location == (location or "--")
                )
            ):
                trace = tr
                break

        if trace is None:
            raise HTTPException(
                404, f"Channel '{channel}' not found in waveform."
            )

        if trim_start and trim_end:
            trace = trace.copy()
            trace.trim(
                UTCDateTime(trim_start),
                UTCDateTime(trim_end),
            )

        # Cache RAM (ephemeral) — HIT tanpa recompute. Parameter config
        # yang memengaruhi hasil (PPSD_LENGTH_SECONDS, PPSD_OVERLAP) ikut
        # dalam key agar perubahan konfigurasi tidak memakai hasil lama.
        cache_key = make_cache_key(
            network, station, location, channel,
            start_time, end_time, trim_start, trim_end, session_id,
            PPSD_LENGTH_SECONDS, PPSD_OVERLAP,
        )
        cached = psd_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "PSD CACHE HIT %s.%s %s", network, station, channel,
            )
            return {
                "network": trace.stats.network or network,
                "station": trace.stats.station or station,
                "location": trace.stats.location or location,
                "channel": trace.stats.channel,
                "psd_image": cached,
            }

        psd_image = compute_psd_image(trace, inventory)
        psd_cache.put(cache_key, psd_image)
        logger.info(
            "PSD CACHE PUT %s.%s %s", network, station, channel,
        )

        return {
            "network": trace.stats.network or network,
            "station": trace.stats.station or station,
            "location": trace.stats.location or location,
            "channel": trace.stats.channel,
            "psd_image": psd_image,
        }

    except WaveformNoDataError as exc:
        logger.exception(
            "PSD no data %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        logger.exception(
            "PSD invalid %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "PSD failed %s.%s %s %s -> %s",
            network, station, channel, start_time, end_time,
        )
        raise HTTPException(status_code=500, detail=str(exc))