import math

import numpy as np
from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNTimeoutException,
)
from app.core.fdsn_client import client
from app.core.config import DECIMATION_DURATION_SECONDS
from app.models.processing import TraceResponse


class WaveformNoDataError(Exception):
    pass

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
    
    try:
        stream = client.get_waveforms(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=starttime,
            endtime=endtime,
        )

    except FDSNNoDataException:
        raise WaveformNoDataError(
            f"No waveform data found for "
            f"{network}.{station}.{location}.{channel}"
        )
    except FDSNTimeoutException:
        raise

    return stream

def _decimate_min_max(data, decimation_factor, num_buckets):
    """
    Min-Max decimation murni vektorisasi NumPy (pad + reshape +
    min/max per axis) - TIDAK ada loop Python sama sekali.

    data di-pad di ujung akhir dengan mode="edge" (mengulang
    nilai sampel terakhir) supaya panjangnya pas kelipatan
    decimation_factor sebelum di-reshape. Ini cuma memengaruhi
    bucket PALING TERAKHIR, dan cuma menambah salinan nilai yang
    memang sudah ada di trace itu sendiri - bukan data fabrikasi,
    bukan nol/NaN yang bisa mendistorsi min/max bucket terakhir.
    """
    pad_length = (
        num_buckets * decimation_factor - len(data)
    )

    padded = (
        np.pad(data, (0, pad_length), mode="edge")
        if pad_length > 0
        else data
    )

    buckets = padded.reshape(num_buckets, decimation_factor)

    return buckets.min(axis=1), buckets.max(axis=1)


def trace_to_json(trace, max_points=None):
    """
    Serialize SATU trace ke dict response.

    Time Bucket decimation (min/max) hanya diterapkan PALING
    AKHIR, yaitu di titik serialisasi ini - SETELAH seluruh
    operasi matematis (filter/trim) berjalan di atas data mentah.

    Keputusan decimate berbasis DURASI, bukan jumlah sampel mentah:
    threshold efektif = DECIMATION_DURATION_SECONDS × sampling_rate.
    Jadi semua channel memulai envelope pada durasi yang sama
    (mis. 5 menit), walau jumlah sampelnya berbeda (20 Hz vs 100 Hz).
    `max_points` tetap dipakai sebagai TARGET resolusi output -
    berapa banyak bucket min/max maksimum yang dikembalikan.
    """
    raw_point_count = len(trace.data)

    stats = None

    if raw_point_count > 0:
        stats = {
            "min": float(trace.data.min()),
            "max": float(trace.data.max()),
        }

    # threshold per trace = durasi × sampling rate channel ini.
    # max_points=None = decimation dimatikan (perilaku lama).
    effective_threshold = (
        DECIMATION_DURATION_SECONDS * trace.stats.sampling_rate
        if max_points is not None
        else None
    )

    should_decimate = (
        effective_threshold is not None
        and raw_point_count > effective_threshold
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
        # Titik per bucket, dihitung supaya jumlah bucket
        # akhir <= max_points (lihat komentar di
        # _decimate_min_max soal padding).
        decimation_factor = math.ceil(
            raw_point_count / max_points
        )
        num_buckets = math.ceil(
            raw_point_count / decimation_factor
        )

        amplitude_min, amplitude_max = _decimate_min_max(
            trace.data,
            decimation_factor,
            num_buckets,
        )

        # Timestamp tiap bucket = AWAL bucket (bukan tengah,
        # bukan posisi sampel min/max asli di dalam bucket) -
        # konvensi ini didokumentasikan eksplisit lewat field
        # bucket_time_reference di response, bukan diam-diam
        # diasumsikan.
        bucket_times = trace.times()[::decimation_factor]

        trace_fields.update({
            "time": [
                (trace.stats.starttime + t).isoformat()
                for t in bucket_times
            ],

            "decimation_method": "minmax",
            "decimation_factor": decimation_factor,
            "bucket_time_reference": "start",
            "returned_point_count": num_buckets,

            "amplitude_min": amplitude_min.tolist(),
            "amplitude_max": amplitude_max.tolist(),
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

    # model_dump(exclude_none=True) yang menegakkan kontrak:
    # field yang tidak relevan untuk kasus ini (mis. amplitude
    # saat decimated=True) benar-benar HILANG dari JSON, bukan
    # cuma bernilai null.
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