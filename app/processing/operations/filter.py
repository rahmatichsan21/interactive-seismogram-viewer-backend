from app.models.processing import FilterOperation


def apply_filter(
    stream,
    operation: FilterOperation,
    context,
):
    working_stream = stream.copy()

    kwargs = {
        "corners": 4,
        "zerophase": True,
    }

    if operation.filter_type in (
        "lowpass",
        "highpass",
    ):
        kwargs["freq"] = operation.freq

    else:
        kwargs["freqmin"] = operation.freqmin
        kwargs["freqmax"] = operation.freqmax

    working_stream.filter(
        operation.filter_type,
        **kwargs,
    )

    return working_stream