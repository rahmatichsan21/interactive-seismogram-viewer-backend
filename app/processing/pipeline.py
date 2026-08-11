from obspy import Stream

from app.processing.registry import OPERATION_REGISTRY
from app.models.processing import Operation
from app.services.processing_cache import processing_cache


def apply_pipeline(
    stream,
    operations: list[Operation],
    context=None,
    cache_info=None,
    ):
    """
    Terapkan pipeline processing ke Stream.

    cache_info (dict | None):
      {"network", "station", "start_time", "end_time"}
      Kalau diisi, snapshot full-resolution Stream akan
      disimpan ke ProcessingCache SEBELUM operation mahal
      (Filter, Instrument Correction) — sehingga Undo bisa
      melanjutkan dari snapshot tanpa replay dari Original.
    """
    working_stream = stream
    ops_processed = []

    for operation in operations:
        op_type = operation.type

        # Snapshot SEBELUM operation ini jika:
        # - ada operation sebelumnya (ops_processed tidak
        #   kosong), DAN
        # - operation sebelumnya atau operation ini sendiri
        #   adalah operation mahal (Filter, dsb).
        # Ini memungkinkan Undo mengambil state setelah
        # prefix yang mengandung Filter, baik operation
        # saat ini adalah Filter (Trim→Filter) maupun bukan
        # Filter (Filter→Trim).
        if cache_info is not None and ops_processed:
            has_expensive = (
                any(
                    op.type in ("filter",)
                    for op in ops_processed
                )
                or op_type in ("filter",)
            )

            if has_expensive:
                key = processing_cache.make_key(
                    network=cache_info["network"],
                    station=cache_info["station"],
                    channel=cache_info["channel"],
                    start_time=cache_info["start_time"],
                    end_time=cache_info["end_time"],
                    operations=ops_processed,
                )

                if not processing_cache.has(key):
                    processing_cache.put(
                        key,
                        Stream.copy(working_stream),
                    )
                    size_mb = sum(
                        tr.data.nbytes for tr in working_stream
                    ) / (1024 * 1024)
                    print(
                        f"[PROC SNAPSHOT] "
                        f"{cache_info['network']}."
                        f"{cache_info['station']}."
                        f"{cache_info['channel']} "
                        f"ops={[op.type for op in ops_processed]} "
                        f"size={size_mb:.1f}MB"
                    )

        handler = OPERATION_REGISTRY[op_type]
        working_stream = handler(
            working_stream,
            operation,
            context,
        )
        ops_processed.append(operation)

    return working_stream