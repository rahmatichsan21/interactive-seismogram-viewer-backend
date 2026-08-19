import math
import socket
import time
import urllib.error

import numpy as np
from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNTimeoutException,
)
from app.core.fdsn_client import client
from app.core.config import MAX_DISPLAY_POINTS
from app.models.processing import TraceResponse


class WaveformNoDataError(Exception):
    pass


# Error transient yang layak dicoba ulang: timeout dan
# kegagalan koneksi/network. FDSNNoDataException TIDAK
# termasuk — data memang tidak tersedia, retry tidak berguna.
try:
    import requests

    _REQUESTS_RETRYABLE = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ProxyError,
        requests.exceptions.SSLError,
    )
except ImportError:
    _REQUESTS_RETRYABLE = ()

RETRYABLE_ERRORS = (
    FDSNTimeoutException,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    urllib.error.URLError,
    *_REQUESTS_RETRYABLE,
)

# Maksimal 3 attempt total (1 percobaan + 2 retry).
MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2


def download_waveform(
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    starttime = UTCDateTime(start_time)
    endtime = UTCDateTime(end_time)

    if endtime <= starttime:
        raise ValueError(
            "End time must be greater than start time."
        )

    last_exc = None

    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            stream = client.get_waveforms(
                network=network,
                station=station,
                location=location,
                channel=channel,
                starttime=starttime,
                endtime=endtime,
            )

            if attempt > 1:
                print(
                    f"[DOWNLOAD SUCCESS] {network}.{station} "
                    f"{location}.{channel} "
                    f"{start_time} -> {end_time} "
                    f"attempt={attempt}"
                )
            return stream

        except FDSNNoDataException:
            raise WaveformNoDataError(
                f"No waveform data found for "
                f"{network}.{station}.{location}.{channel}"
            )

        except RETRYABLE_ERRORS as exc:
            last_exc = exc
            print(
                f"[DOWNLOAD RETRY] {network}.{station} "
                f"{location}.{channel} "
                f"{start_time} -> {end_time} "
                f"attempt={attempt}/{MAX_DOWNLOAD_ATTEMPTS} "
                f"reason={type(exc).__name__}"
            )
            if attempt < MAX_DOWNLOAD_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

        except Exception as exc:
            print(
                f"[DOWNLOAD FAILED] {network}.{station} "
                f"{location}.{channel} "
                f"{start_time} -> {end_time} "
                f"reason={type(exc).__name__}: {exc}"
            )
            raise

    # Semua retry habis untuk error transient — propagate
    # exception terakhir supaya caller tahu kegagalan.
    raise last_exc

def _decimate_temporal(data, decimation_factor, num_buckets):
    """
    Temporal-order Min/Max decimation — memilih sampel asli
    pada posisi argmin & argmax setiap bucket, lalu mengurutkan
    hasilnya berdasarkan urutan waktu asli (bukan bucket).

    Tidak mengambil semua sampel; tidak membuat envelope;
    output adalah subhimpunan yang tersebar di sepanjang trace
    dengan prioritas pada titik-titik dengan amplitudo ekstrem —
    baik positif maupun negatif.

    Seluruhnya vektorisasi NumPy (pad + reshape + argmin/argmax
    + merge-sort) — TIDAK ada loop Python untuk iterasi bucket.
    """
    pad_length = num_buckets * decimation_factor - len(data)

    padded = (
        np.pad(data, (0, pad_length), mode="edge")
        if pad_length > 0
        else data
    )

    buckets = padded.reshape(num_buckets, decimation_factor)

    idx_min = buckets.argmin(axis=1)
    idx_max = buckets.argmax(axis=1)

    offset = np.arange(num_buckets) * decimation_factor

    return np.unique(
        np.sort(
            np.concatenate([offset + idx_min, offset + idx_max])
        )
    )


def trace_to_json(trace, max_points=None):
    """
    Serialize SATU trace ke dict response.

    Time Bucket decimation (temporal-order min/max) hanya
    diterapkan PALING AKHIR, yaitu di titik serialisasi ini —
    SETELAH seluruh operasi matematis (filter/trim) berjalan
    di atas data mentah.

    Trigger: raw_point_count > MAX_DISPLAY_POINTS.
    Target output: `max_points` bucket, masing-masing
    menghasilkan hingga 2 titik (argmin + argmax), sehingga
    output akhir ≈ 2 × max_points ≈ MAX_DISPLAY_POINTS.

    Output SELALU menggunakan format `time[]` + `amplitude[]`,
    baik raw maupun decimated. Decimation adalah
    detail implementasi internal yang tidak mengubah skema
    response.
    """
    raw_point_count = len(trace.data)

    stats = None

    if raw_point_count > 0:
        stats = {
            "min": float(trace.data.min()),
            "max": float(trace.data.max()),
        }

    # Trigger: raw_point_count > MAX_DISPLAY_POINTS.
    # max_points=None = decimation dimatikan (benchmark).
    should_decimate = (
        max_points is not None
        and raw_point_count > MAX_DISPLAY_POINTS
    )

    trace_fields = {
        "location": trace.stats.location,
        "channel": trace.stats.channel,
        "sampling_rate": trace.stats.sampling_rate,

        "decimated": should_decimate,
        "raw_point_count": raw_point_count,
        "requested_max_points": max_points,

        "stats": stats,
    }

    if should_decimate:
        decimation_factor = math.ceil(
            raw_point_count / max_points
        )
        num_buckets = math.ceil(
            raw_point_count / decimation_factor
        )

        selected_indices = _decimate_temporal(
            trace.data,
            decimation_factor,
            num_buckets,
        )

        all_times = trace.times()

        returned_point_count = len(selected_indices)

        trace_fields.update({
            "time": [
                (trace.stats.starttime + all_times[i]).isoformat()
                for i in selected_indices
            ],

            "returned_point_count": returned_point_count,

            "amplitude": trace.data[selected_indices].tolist(),
        })

    else:
        trace_fields.update({
            "time": [
                (trace.stats.starttime + t).isoformat()
                for t in trace.times()
            ],

            "returned_point_count": raw_point_count,

            "amplitude": trace.data.tolist(),
        })

    return TraceResponse(**trace_fields).model_dump(
        exclude_none=True
    )


def stream_to_json(stream, station, max_points=None):
    """
    Serialize seluruh Stream menjadi response {"station", "traces"}.
    Decimation (kalau `max_points` diisi) diterapkan per trace di
    trace_to_json() - yang selalu berjalan setelah operasi apa pun.
    """
    traces = [
        trace_to_json(trace, max_points)
        for trace in stream
    ]

    return {

        "station": station,

        "traces": traces

    }