from app.processing.registry import OPERATION_REGISTRY

def apply_pipeline(stream, operations, context=None):

    working_stream = stream

    for operation in operations:

        operation_type = operation["type"]

        handler = OPERATION_REGISTRY[operation_type]

        working_stream = handler(
            working_stream,
            operation,
            context,
        )

    return working_stream