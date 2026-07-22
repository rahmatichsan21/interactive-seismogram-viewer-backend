import pandas as pd

from obspy.clients.fdsn import Client
from app.services.inventory_service import get_inventory
from app.core.config import (
    BMKG_URL,
    BMKG_USERNAME,
    BMKG_PASSWORD,
    DEFAULT_NETWORK,
    STATION_CSV,
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

    inventory = get_inventory(
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

def download_station_csv():
    inventory = client.get_stations(
        network=DEFAULT_NETWORK,
        level="station",
    )

    rows = []

    for network in inventory:
        for station in network:

            rows.append(
                {
                    "net": network.code,
                    "kode_stasiun": station.code,
                }
            )

    dataframe = (
        pd.DataFrame(rows)
        .drop_duplicates()
        .sort_values("kode_stasiun")
    )

    dataframe.to_csv(
        STATION_CSV,
        index=False,
    )