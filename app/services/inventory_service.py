from app.core.fdsn_client import client
from obspy import UTCDateTime
from app.core.config import (
    BMKG_URL,
    BMKG_USERNAME,
    BMKG_PASSWORD,
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

def iter_networks(inventory):
    """
    Iterate over every network in an ObsPy Inventory.
    """
    for network in inventory:
        yield network


def iter_stations(inventory):
    """
    Iterate over every station in an ObsPy Inventory.
    """
    for network in inventory:
        for station in network:
            yield network, station


def iter_channels(inventory):
    """
    Iterate over every channel in an ObsPy Inventory.
    """
    for network in inventory:
        for station in network:
            for channel in station:
                yield network, station, channel

def unique_channels(inventory):
    """
    Return sorted unique channel codes.
    """
    return sorted({
        channel.code
        for _, _, channel in iter_channels(inventory)
    })

def unique_locations(inventory):
    """
    Return sorted unique location codes.
    """
    return sorted({
        channel.location_code or "--"
        for _, _, channel in iter_channels(inventory)
    })

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

    return unique_channels(inventory)