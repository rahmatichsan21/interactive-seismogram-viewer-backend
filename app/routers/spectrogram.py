import base64
import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from obspy.imaging.spectrogram import (
    spectrogram as obspy_spectrogram,
)
from obspy import Stream
from scipy.signal import spectrogram as scipy_spectrogram

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from obspy import UTCDateTime

from app.core.database import get_db
from app.services.waveform_provider_service import get_waveform
from app.services.upload_storage import get_stream as get_upload_stream
from app.services.ttl_cache import make_cache_key, spectrogram_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Spectrogram"])


def _has_masked_gap(trace):
    """True hanya bila trace memiliki minimal satu sampel gap masked."""
    return (
        np.ma.isMaskedArray(trace.data)
        and np.ma.getmaskarray(trace.data).any()
    )


def _render_gap_aware_spectrogram(ax, trace, wlen):
    """Render tiap segmen valid tanpa menggambar energi pada gap.

    ObsPy spectrogram menerima satu array kontinu. Jika array masked
    diberikan langsung, gap dapat terinterpretasi sebagai nilai data.
    Karena itu hanya trace bergap yang di-split sementara di sini.
    Posisi tiap hasil spectrogram dikembalikan ke offset waktu aslinya;
    area gap tidak menerima artist apa pun dan tetap kosong.
    """
    spectra = []
    target_nperseg = max(
        2,
        int(round(wlen * trace.stats.sampling_rate)),
    )

    for segment in Stream(traces=[trace]).split():
        data = np.asarray(segment.data)
        if len(data) < 2:
            continue

        nperseg = min(target_nperseg, len(data))
        noverlap = min(
            nperseg - 1,
            int(nperseg * 0.5),
        )
        frequencies, times, power = scipy_spectrogram(
            data,
            fs=segment.stats.sampling_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            scaling="density",
            mode="psd",
        )

        if power.size == 0:
            continue

        power_db = 10 * np.log10(
            np.maximum(power, np.finfo(float).tiny)
        )
        offset_seconds = float(
            segment.stats.starttime - trace.stats.starttime
        )
        spectra.append((frequencies, times + offset_seconds, power_db))

    if not spectra:
        raise HTTPException(
            400,
            "Spectrogram tidak dapat dibuat karena tidak ada segmen waveform valid.",
        )

    vmin = min(power_db.min() for _, _, power_db in spectra)
    vmax = max(power_db.max() for _, _, power_db in spectra)
    if vmin == vmax:
        vmax = vmin + 1

    image = None
    for frequencies, times, power_db in spectra:
        image = ax.pcolormesh(
            times,
            frequencies,
            power_db,
            shading="auto",
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
        )

    ax.set_facecolor("white")
    ax.set_xlim(
        0,
        len(trace.data) / trace.stats.sampling_rate,
    )
    return image


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
        # Sama seperti FDSN (waveform_provider_service._assemble_and_trim)
        # dan endpoint display upload (upload.get_upload_waveform): gabung
        # per channel dan pertahankan gap sebagai masked trace, supaya
        # satu station+channel SELALU 1 logical waveform (1 trace), bukan
        # beberapa trace terpisah per segmen kontinu. Tanpa merge ini,
        # seleksi trace di bawah hanya mengambil segmen PERTAMA (tidak
        # masked), sehingga _has_masked_gap() selalu False dan gap tidak
        # pernah dirender untuk Local Upload walau waveform-nya bergap.
        # Merge dilakukan pada SALINAN stream — sesi upload asli (dipakai
        # processing/validation/export) tidak berubah.
        stream = stream.copy()
        stream.merge(method=1, fill_value=None)
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

    # 3. Pilih trace berdasarkan identity lengkap. Untuk local upload,
    # satu session dapat memiliki beberapa station dengan channel sama;
    # memilih channel saja akan selalu mengambil trace pertama.
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
            404,
            "Trace tidak ditemukan untuk identity "
            f"{network}.{station}.{location}.{channel}.",
        )

    # Cache RAM (ephemeral) — HIT tanpa recompute.
    cache_key = make_cache_key(
        "gap-aware-v1",
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

    if _has_masked_gap(trace):
        image = _render_gap_aware_spectrogram(
            ax,
            trace,
            wlen,
        )
    else:
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