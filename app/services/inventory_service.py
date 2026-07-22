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


def get_inventory(
    network,
    station,
    location="*",
    channel="*",
    starttime=None,
    endtime=None,
    level="channel",
):
    return client.get_stations(
        network=network,
        station=station,
        location=location,
        channel=channel,
        starttime=starttime,
        endtime=endtime,
        level=level,
    )

def get_available_channels(
    network,
    station,
    start_time,
    end_time,
    ):
    inventory = get_inventory(
        network=network,
        station=station,
        location="*",
        channel="*",
        starttime=UTCDateTime(start_time),
        endtime=UTCDateTime(end_time),
        level="channel",
    )

    return sorted({
        channel.code
        for network_item in inventory
        for station_item in network_item
        for channel in station_item
    })