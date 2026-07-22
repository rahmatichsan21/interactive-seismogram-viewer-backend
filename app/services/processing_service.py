from app.processing.pipeline import apply_pipeline


def process_stream(stream, operations, context=None):
    working_stream = stream.copy()

    return apply_pipeline(
        working_stream,
        operations,
        context,
    )