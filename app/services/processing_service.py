import logging

import numpy as np
from obspy import Stream

from app.core.config import GAP_THRESHOLD_PERCENT
from app.models.processing import Operation
from app.processing.pipeline import apply_pipeline
from app.services.processing_cache import processing_cache

logger = logging.getLogger(__name__)


def _log_significant_gaps(trace):
    """Log gap individual yang melebihi threshold konfigurasi.

    Threshold dihitung untuk SETIAP run gap terhadap jumlah sampel
    trace, bukan akumulasi semua gap. Ia bersifat observability;
    semua masked trace tetap harus di-split agar operasi ObsPy aman.
    """
    if not np.ma.isMaskedArray(trace.data):
        return

    mask = np.ma.getmaskarray(trace.data)
    if not mask.any() or len(mask) == 0:
        return

    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(int)))

    for start, end in zip(edges[::2], edges[1::2]):
        gap_percent = (end - start) / len(mask) * 100
        if gap_percent >= GAP_THRESHOLD_PERCENT:
            logger.info(
                "GAP SIGNIFIKAN %s: %.2f%% (%d sampel, %s -> %s)",
                trace.id,
                gap_percent,
                end - start,
                trace.stats.starttime + start / trace.stats.sampling_rate,
                trace.stats.starttime + end / trace.stats.sampling_rate,
            )


def _merge_channel_segments(processed_segments: Stream) -> Stream:
    """Gabungkan kembali segmen valid dan isi posisi gap dengan nol."""
    if len(processed_segments) == 0:
        return processed_segments

    merged = processed_segments.copy()
    merged.merge(method=1, fill_value=0)
    return merged


def process_waveform(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
) -> Stream:
    """Process stream masked dengan split internal lalu merge nol.

    Urutan wajib untuk trace bergap adalah:
    merge(masked) -> split() -> process setiap segmen -> merge(fill=0).
    Cache intermediate pipeline sengaja tidak dipakai di sini: cache
    hanya aman disimpan setelah semua segmen kembali menjadi satu trace
    channel final.
    """
    if context is None:
        context = {}

    masked_stream = stream.copy()
    masked_stream.merge(method=1, fill_value=None)

    for trace in masked_stream:
        _log_significant_gaps(trace)

    valid_segments = masked_stream.split()
    processed_segments = Stream()

    for segment in valid_segments:
        processed_segments += apply_pipeline(
            stream=Stream(traces=[segment]),
            operations=operations,
            context=context,
        )

    return _merge_channel_segments(processed_segments)


def _iter_channels(stream: Stream):
    """Yield satu Stream masked untuk setiap identity trace/channel."""
    channels = {}

    for trace in stream:
        channels.setdefault(trace.id, Stream()).append(trace.copy())

    for channel_stream in channels.values():
        channel_stream.merge(method=1, fill_value=None)
        for trace in channel_stream:
            yield Stream(traces=[trace])


def process_waveform_per_channel(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
    cache_info: dict | None = None,
):
    """Proses satu channel final pada satu waktu untuk membatasi RAM.

    Cache menyimpan hasil akhir channel yang sudah di-merge(fill_value=0),
    bukan segmen internal. Karena itu cache key tidak memakai segment index.
    """
    for channel_stream in _iter_channels(stream):
        source_trace = channel_stream[0]
        channel = source_trace.stats.channel or ""
        station = source_trace.stats.station or ""
        network = source_trace.stats.network or ""
        location = source_trace.stats.location or "--"

        trace_cache_info = None
        final_key = None
        if cache_info is not None and operations:
            trace_cache_info = {
                **cache_info,
                # Local session dapat berisi beberapa station dengan
                # channel sama. Cache harus memakai identity trace
                # aktual, bukan station dari request pertama.
                "network": network or cache_info["network"],
                "station": station or cache_info["station"],
                "location": location,
                "channel": channel,
            }
            final_key = processing_cache.make_key(
                network=trace_cache_info["network"],
                station=trace_cache_info["station"],
                location=trace_cache_info["location"],
                channel=channel,
                start_time=trace_cache_info["start_time"],
                end_time=trace_cache_info["end_time"],
                operations=operations,
            )
            cached = processing_cache.get(final_key)
            if cached is not None:
                logger.debug(
                    "PROC CACHE HIT %s.%s.%s ops=%s",
                    trace_cache_info["network"],
                    trace_cache_info["station"],
                    channel,
                    [op.type for op in operations],
                )
                yield cached.traces[0].copy()
                continue

        processed = process_waveform(
            stream=channel_stream,
            operations=operations,
            context=context,
        )

        if len(processed) == 0:
            continue

        processed_trace = processed[0]

        if final_key is not None and not processing_cache.has(final_key):
            processing_cache.put(final_key, Stream(traces=[processed_trace.copy()]))
            size_mb = processed_trace.data.nbytes / (1024 * 1024)
            logger.debug(
                "PROC FINAL %s.%s.%s ops=%s size=%.1fMB",
                trace_cache_info["network"],
                trace_cache_info["station"],
                channel,
                [op.type for op in operations],
                size_mb,
            )

        yield processed_trace
