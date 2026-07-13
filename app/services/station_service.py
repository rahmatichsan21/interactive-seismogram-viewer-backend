import pandas as pd

from app.core.config import STATION_CSV
from obspy.clients.fdsn import Client

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


def get_all_stations():

    df = pd.read_csv(STATION_CSV)

    df = df[["net", "kode_stasiun"]]

    df = df.dropna()

    df = df.sort_values("kode_stasiun")

    return df.to_dict(orient="records")


def get_station_info(network, station):

    inventory = client.get_stations(
        network=network,
        station=station,
        level="channel",
    )

    locations = set()
    channels = set()

    for net in inventory:
        for sta in net:
            for ch in sta:

                locations.add(ch.location_code or "*")
                channels.add(ch.code)

    return {
        "locations": sorted(locations),
        "channels": sorted(channels),
    }