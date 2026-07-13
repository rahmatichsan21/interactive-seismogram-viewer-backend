from obspy.clients.fdsn import Client
from obspy import UTCDateTime

from app.core.config import (
    BMKG_URL,
    BMKG_USERNAME,
    BMKG_PASSWORD,
)


client = Client(
    BMKG_URL,
    user=BMKG_USERNAME,
    password=BMKG_PASSWORD,
)

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

    stream = client.get_waveforms(
        network=network,
        station=station,
        location=location,
        channel=channel,
        starttime=starttime,
        endtime=endtime,
    )

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