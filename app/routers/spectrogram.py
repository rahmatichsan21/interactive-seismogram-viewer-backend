import base64
import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from obspy.imaging.spectrogram import (
    spectrogram as obspy_spectrogram,
)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from obspy import UTCDateTime

from app.core.database import get_db
from app.services.waveform_provider_service import get_waveform
from app.services.upload_storage import get_stream as get_upload_stream
from app.services.ttl_cache import make_cache_key, spectrogram_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Spectrogram"])


@router.get("/spectrogram")
def get_spectrogram(
    network: str = None,
    station: str = None,
    location: str = None,
    channel: str = Query(...),
    start_time: str = None,
    end_time: str = None,
    session_id: str = None,
    trim_start: str = None,
    trim_end: str = None,
    db: Session = Depends(get_db),
):
    """
    Generate spectrogram dari RAW full-resolution waveform.

    Mendukung FDSN (network/station/location/start_time/end_time)
    dan Local File (session_id). Trim hanya mengubah rentang
    waktu — Filter TIDAK diterapkan. Hasil berupa base64 PNG.
    """
    logger.info(
        "Spectrogram %s.%s %s (session=%s)",
        network, station, channel, session_id,
    )

    # 1. Get raw full-resolution Stream
    if session_id:
        stream = get_upload_stream(session_id)
        if stream is None:
            raise HTTPException(
                404, "Upload session not found."
            )
    elif network and station and start_time and end_time:
        stream = get_waveform(
            db=db,
            network=network,
            station=station,
            location=location or "*",
            channel=channel,
            start_time=start_time,
            end_time=end_time,
        )
    else:
        raise HTTPException(
            400,
            "Provide either session_id or "
            "(network, station, start_time, end_time).",
        )

    # 2. Apply Trim to RAW (only Trim, no Filter)
    if trim_start and trim_end:
        stream = stream.copy()
        stream.trim(
            UTCDateTime(trim_start),
            UTCDateTime(trim_end),
        )

    # 3. Select the requested channel
    found = False
    for tr in stream:
        if tr.stats.channel == channel:
            trace = tr
            found = True
            break

    if not found:
        raise HTTPException(
            404, f"Channel '{channel}' not found in stream."
        )

    # Cache RAM (ephemeral) — HIT tanpa recompute.
    cache_key = make_cache_key(
        network, station, location, channel,
        start_time, end_time, trim_start, trim_end, session_id,
    )
    cached = spectrogram_cache.get(cache_key)
    if cached is not None:
        logger.info("SPECTROGRAM CACHE HIT %s.%s %s", network, station, channel)
        return {
            "channel": channel,
            "spectrogram": cached,
        }

    # 4. Compute spectrogram dari raw full-resolution data.
    duration = len(trace.data) / trace.stats.sampling_rate
    wlen = max(
        duration / 1000.0,
        128.0 / trace.stats.sampling_rate,
    )

    # Figure horizontal agar area data Spectrogram mengikuti
    # proporsi area plotting Waveform (lebar mendominasi), bukan
    # kotak kecil. Axes dibuat eksplisit dan diteruskan ke
    # obspy_spectrogram() — algoritma PSD/spectrogram tidak
    # berubah, hanya figure/axes layout. Aspect imshow default
    # ('equal') dipertahankan sehingga sumbu waktu/frekuensi
    # tidak terdistorsi.
    fig = plt.figure(figsize=(12, 3))
    ax = fig.add_subplot(111)

    obspy_spectrogram(
        trace.data,
        samp_rate=trace.stats.sampling_rate,
        per_lap=0.5,
        wlen=wlen,
        dbscale=True,
        cmap="viridis",
        title=(
            f"{trace.stats.network}.{trace.stats.station}."
            f"{trace.stats.channel}"
        ),
        show=False,
        axes=ax,
    )

    # Ketika `axes` diteruskan, obspy_spectrogram() mengembalikan
    # lebih awal dan TIDAK mengatur label sumbu/title. Set ulang
    # di sini supaya output identik dengan perilaku sebelumnya
    # (tanpa `axes`), selain ukuran figure yang kini horizontal.
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Frequency [Hz]")
    ax.set_title(
        f"{trace.stats.network}.{trace.stats.station}."
        f"{trace.stats.channel}"
    )

    # 5. Render ke PNG → base64
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)

    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    spectrogram_cache.put(cache_key, b64)
    logger.info("SPECTROGRAM CACHE PUT %s.%s %s", network, station, channel)
    return {
        "channel": channel,
        "spectrogram": b64,
    }
