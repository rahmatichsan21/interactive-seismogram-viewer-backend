import math

import numpy as np
from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNTimeoutException,
)
from app.core.fdsn_client import client
from app.models.processing import TraceResponse


MIN_MAX_POINTS = 100
MAX_MAX_POINTS = 20000




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

def clamp_max_points(max_points):
    """
    Sengaja CLAMP, bukan tolak/422 - permintaan eksplisit di
    kesepakatan API contract. max_points di luar rentang wajar
    disesuaikan diam-diam ke batas terdekat, bukan bikin request
    gagal cuma karena angka resolusi layar yang sedikit meleset.
    """
    if max_points is None:
        return None

    return max(
        MIN_MAX_POINTS,
        min(MAX_MAX_POINTS, max_points),
    )


def _decimate_min_max(data, decimation_factor, num_buckets):
    """
    Min-Max decimation murni vektorisasi NumPy (pad + reshape +
    min/max per axis) - TIDAK ada loop Python sama sekali,
    sesuai permintaan.

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
    Serialize + decimate SATU trace. Diekstrak dari badan
    for-loop stream_to_json() di bawah - isinya PERSIS sama,
    cuma dipisah supaya bisa dipanggil langsung per-channel oleh
    process_waveform_per_channel() di router (lihat
    routers/processing.py), tanpa perlu menunggu seluruh Stream
    multi-channel selesai diproses lebih dulu.

    max_points di sini diasumsikan SUDAH di-clamp oleh
    pemanggilnya (stream_to_json melakukan ini untuk
    pemanggilnya sendiri; router juga clamp sekali di awal untuk
    jalur per-channel) - fungsi ini sendiri tidak clamp ulang,
    supaya tidak clamp dobel dari dua tempat berbeda.
    """
    raw_point_count = len(trace.data)

    stats = None

    if raw_point_count > 0:
        stats = {
            "min": float(trace.data.min()),
            "max": float(trace.data.max()),
        }

    should_decimate = (
        max_points is not None
        and raw_point_count > max_points
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

    # model_dump(exclude_none=True) yang menegakkan kontrak
    # Fail Loud: field yang tidak relevan untuk kasus ini
    # (mis. amplitude_min saat decimated=False) benar-benar
    # HILANG dari JSON, bukan cuma bernilai null.
    return TraceResponse(**trace_fields).model_dump(
        exclude_none=True
    )


def stream_to_json(stream, station, max_points=None):
    """
    Dipertahankan untuk pemanggil yang tidak butuh optimasi
    per-channel (mis. /api/waveform, endpoint load awal yang
    belum direfaktor - lihat catatan gap di sesi sebelumnya).
    Perilakunya IDENTIK dengan sebelum trace_to_json() diekstrak
    - cuma sekarang badan loopnya delegasi ke trace_to_json().
    """
    max_points = clamp_max_points(max_points)

    traces = [
        trace_to_json(trace, max_points)
        for trace in stream
    ]

    return {

        "station": station,

        "traces": traces

    }