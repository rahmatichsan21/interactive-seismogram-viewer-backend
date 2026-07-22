from obspy import Stream

from app.processing.pipeline import apply_pipeline


def process_waveform(
    stream: Stream,
    operations: list,
    context: dict | None = None,
) -> Stream:
    """
    Process an ObsPy Stream using the processing pipeline.
    """

    if context is None:
        context = {}

    # Housekeeping
    stream.merge()

    processed_stream = apply_pipeline(
        stream=stream,
        operations=operations,
        context=context,
    )

    return processed_stream