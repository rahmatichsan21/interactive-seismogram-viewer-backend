from app.models.processing import Operation
from app.processing.registry import OPERATION_REGISTRY


def apply_pipeline(
    stream,
    operations: list[Operation],
    context=None,
):
    """Terapkan operasi secara berurutan pada satu segmen valid.

    Gap ditangani di processing_service: masked trace di-split sebelum
    fungsi ini dipanggil, lalu seluruh hasil segmen di-merge(fill_value=0).
    ProcessingCache juga dikelola di processing_service agar hanya hasil
    akhir satu trace/channel yang pernah disimpan atau digunakan ulang.
    """
    working_stream = stream

    for operation in operations:
        handler = OPERATION_REGISTRY[operation.type]
        working_stream = handler(
            working_stream,
            operation,
            context,
        )

    return working_stream
