from app.models.processing import FilterOperation
from fastapi import HTTPException


def apply_filter(
    stream,
    operation: FilterOperation,
    context,
):
    working_stream = stream.copy()

    kwargs = {
        "corners": operation.corners,
        "zerophase": operation.zerophase,
    }
    if operation.filter_type in (
        "lowpass",
        "highpass",
    ):
        kwargs["freq"] = operation.freq

    else:
        kwargs["freqmin"] = operation.freqmin
        kwargs["freqmax"] = operation.freqmax

    for trace in working_stream:
        nyquist = trace.stats.sampling_rate / 2

        if (
            operation.filter_type == "bandpass"
            and operation.freqmax >= nyquist
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{trace.id}: "
                    f"Maximum frequency ({operation.freqmax} Hz) "
                    f"must be lower than Nyquist "
                    f"({nyquist:.2f} Hz)."
                ),
            )

        if (
            operation.filter_type == "lowpass"
            and operation.freq >= nyquist
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{trace.id}: "
                    f"Frequency ({operation.freq} Hz) "
                    f"must be lower than Nyquist "
                    f"({nyquist:.2f} Hz)."
                ),
            )
    working_stream.filter(
        operation.filter_type,
        **kwargs,
    )

    return working_stream