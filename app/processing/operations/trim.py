from obspy import UTCDateTime


def apply_trim(stream, operation, context):
    """
    Trim an ObsPy Stream.
    """
    try:
        start_time = UTCDateTime(operation["start_time"])
        end_time = UTCDateTime(operation["end_time"])
    except KeyError as exc:
        raise ValueError("trim butuh start_time dan end_time") from exc

    if end_time <= start_time:
        raise ValueError("end_time harus lebih besar dari start_time")

    working_stream = stream.copy()
    working_stream.trim(
        starttime=start_time,
        endtime=end_time,
    )

    return working_stream