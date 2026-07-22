import pandas as pd

from app.core.fdsn_client import client
from app.services.inventory_service import (
    get_inventory,
    unique_channels,
    unique_locations,
)
from app.core.config import (
    DEFAULT_NETWORK,
    STATION_CSV,
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

    return {
        "locations": unique_locations(inventory),
        "channels": unique_channels(inventory),
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