from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNTimeoutException,
)
from app.core.fdsn_client import client




class WaveformNoDataError(Exception):
    pass

def download_waveform(
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    starttime = UTCDateTime(start_time)
    endtime = UTCDateTime(end_time)

    if endtime <= starttime:
        raise ValueError(
            "End time must be greater than start time."
        )
    
    try:
        stream = client.get_waveforms(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=starttime,
            endtime=endtime,
        )

    except FDSNNoDataException:
        raise WaveformNoDataError(
            f"No waveform data found for "
            f"{network}.{station}.{location}.{channel}"
        )
    except FDSNTimeoutException:
        raise

    return stream

def stream_to_json(stream, station):

    traces = []

    for trace in stream:

        traces.append({
            "location": trace.stats.location,
            "channel": trace.stats.channel,

            "time": [
                (trace.stats.starttime + t).isoformat()
                for t in trace.times()
            ],

            "amplitude": trace.data.tolist()
        })
    return {

        "station": station,

        "traces": traces

    }