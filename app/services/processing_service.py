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