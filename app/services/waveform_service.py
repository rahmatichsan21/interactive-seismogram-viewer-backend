from obspy.clients.fdsn import Client
from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNTimeoutException,
)
from app.services.inventory_service import get_inventory
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

class WaveformNoDataError(Exception):
    pass

def check_channel_available(
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    starttime = UTCDateTime(start_time)
    endtime = UTCDateTime(end_time)

    try:
        inventory = get_inventory(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=starttime,
            endtime=endtime,
            level="channel",
        )

        # Pastikan inventory benar-benar memiliki channel
        channel_count = sum(
            1
            for network_item in inventory
            for station_item in network_item
            for _ in station_item
        )

        return channel_count > 0

    except FDSNNoDataException:
        return False

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