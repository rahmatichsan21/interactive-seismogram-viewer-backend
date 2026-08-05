from obspy import Stream

from app.processing.pipeline import apply_pipeline
from app.models.processing import Operation


def process_waveform(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
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
    )

    return processed_stream


def process_waveform_per_channel(
    stream: Stream,
    operations: list[Operation],
    context: dict | None = None,
):
    """
    Generator - proses satu channel (trace) pada satu waktu,
    lalu langsung yield hasilnya, SEBELUM lanjut ke channel
    berikutnya.

    Alasan pakai `yield` (bukan mengumpulkan semua hasil ke
    dalam list lalu return sekaligus): supaya cuma SATU channel
    yang "in flight" di memori pada satu waktu. Caller (router)
    WAJIB meng-consume tiap hasil (mis. langsung serialize +
    decimate lewat trace_to_json) sebelum generator ini lanjut
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
    for trace in stream:
        single_channel_stream = Stream(traces=[trace])

        processed = process_waveform(
            stream=single_channel_stream,
            operations=operations,
            context=context,
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