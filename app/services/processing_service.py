import logging

from obspy import Stream

from app.processing.pipeline import apply_pipeline
from app.models.processing import Operation

logger = logging.getLogger(__name__)


def process_waveform(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
    cache_info: dict | None = None,
) -> Stream:
    """
    Process an ObsPy Stream using the processing pipeline.
    """

    if context is None:
        context = {}

    # Housekeeping
    working_stream = stream.copy()
    working_stream.merge()

    processed_stream = apply_pipeline(
        stream=working_stream,
        operations=operations,
        context=context,
        cache_info=cache_info,
    )

    return processed_stream


def process_waveform_per_channel(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
    cache_info: dict | None = None,
):
    """
    Generator - proses satu channel (trace) pada satu waktu,
    lalu langsung yield hasilnya, SEBELUM lanjut ke channel
    berikutnya.

    Sebelum memproses setiap trace, cek ProcessingCache:
    kalau snapshot untuk pipeline ini sudah ada, pakai
    langsung tanpa replay dari Original.

    Alasan pakai `yield` (bukan mengumpulkan semua hasil ke
    dalam list lalu return sekaligus): supaya cuma SATU channel
    yang "in flight" di memori pada satu waktu. Caller (router)
    WAJIB meng-consume tiap hasil (mis. langsung serialize lewat
    trace_to_json) sebelum generator ini lanjut
    ke channel berikutnya - ini bukan konvensi yang bisa
    dilanggar diam-diam, tapi properti struktural dari generator
    itu sendiri.

    Sengaja TIDAK mengubah process_waveform() di atas maupun
    apply_pipeline()/operation handler (trim.py, filter.py) -
    filtering ObsPy sudah per-trace independen di baliknya,
    jadi memanggil process_waveform() sekali per channel (Stream
    berisi 1 trace) menghasilkan output yang identik secara
    matematis dengan memanggilnya sekali untuk seluruh Stream
    multi-channel. Ini murni perubahan orkestrasi, bukan logika.
    """
    from app.services.processing_cache import processing_cache

    for trace in stream:
        channel = trace.stats.channel or ""

        # Cek ProcessingCache untuk trace ini.
        # Kalau pipeline SUDAH punya snapshot, langsung pakai.
        if cache_info is not None and operations:
            trace_cache_info = {
                **cache_info,
                "channel": channel,
            }
            key = processing_cache.make_key(
                network=trace_cache_info["network"],
                station=trace_cache_info["station"],
                channel=channel,
                start_time=trace_cache_info["start_time"],
                end_time=trace_cache_info["end_time"],
                operations=operations,
            )

            cached = processing_cache.get(key)
            if cached is not None:
                logger.debug(
                    "PROC CACHE HIT %s.%s.%s ops=%s",
                    trace_cache_info["network"],
                    trace_cache_info["station"],
                    channel,
                    [op.type for op in operations],
                )
                yield cached.traces[0]
                continue

        single_channel_stream = Stream(traces=[trace])

        trace_cache_info_for_pipeline = None
        if cache_info is not None:
            trace_cache_info_for_pipeline = {
                **cache_info,
                "channel": channel,
            }

        processed = process_waveform(
            stream=single_channel_stream,
            operations=operations,
            context=context,
            cache_info=trace_cache_info_for_pipeline,
        )

        # Simpan hasil FINAL pipeline ke ProcessingCache.
        # Ini memungkinkan Undo antar history state
        # (mis. edit Filter param) langsung HIT tanpa
        # replay dari Original.
        if cache_info is not None and operations:
            final_key = processing_cache.make_key(
                network=trace_cache_info["network"],
                station=trace_cache_info["station"],
                channel=channel,
                start_time=trace_cache_info["start_time"],
                end_time=trace_cache_info["end_time"],
                operations=operations,
            )

            if not processing_cache.has(final_key):
                processing_cache.put(
                    final_key,
                    Stream.copy(processed),
                )
                size_mb = sum(
                    tr.data.nbytes for tr in processed
                ) / (1024 * 1024)
                logger.debug(
                    "PROC FINAL %s.%s.%s ops=%s size=%.1fMB",
                    trace_cache_info["network"],
                    trace_cache_info["station"],
                    channel,
                    [op.type for op in operations],
                    size_mb,
                )

        yield processed.traces[0]

        # Baris di bawah ini baru dieksekusi SETELAH caller
        # selesai meng-consume hasil yield di atas (mis. sudah
        # selesai memanggil trace_to_json dan meng-append
        # hasilnya). CPython pakai reference counting - begitu
        # kedua variabel ini di-del dan tidak ada referensi lain
        # yang menggantung ke objeknya, memorinya dibebaskan
        # SEKETIKA, bukan menunggu siklus garbage collector.
        del single_channel_stream
        del processed