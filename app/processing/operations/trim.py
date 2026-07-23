from obspy import UTCDateTime

from app.models.processing import TrimOperation


def apply_trim(
    stream,
    operation: TrimOperation,
    context,
):
    """
    Trim an ObsPy Stream.
    """
    start_time = UTCDateTime(operation.start_time)
    end_time = UTCDateTime(operation.end_time)

    if end_time <= start_time:
        raise ValueError("end_time harus lebih besar dari start_time")

    working_stream = stream.copy()
    working_stream.trim(
        starttime=start_time,
        endtime=end_time,
    )

    return working_stream