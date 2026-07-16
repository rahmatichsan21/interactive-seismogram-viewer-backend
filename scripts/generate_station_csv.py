import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNUnauthorizedException,
    FDSNForbiddenException,
)

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


def check_station(network, station):

    start = UTCDateTime() - 60
    end = start + 1

    try:

        client.get_waveforms(
            network=network,
            station=station,
            location="*",
            channel="*",
            starttime=start,
            endtime=end,
        )

        return True

    except FDSNNoDataException:
        # Server menerima credential, hanya tidak ada data
        return True

    except (
        FDSNUnauthorizedException,
        FDSNForbiddenException,
    ):
        return False

    except Exception as error:
        print(f"ERROR {network}.{station} : {error}")
        return False


def generate_csv():

    inventory = client.get_stations(
        network=DEFAULT_NETWORK,
        level="station",
    )

    total = sum(len(net) for net in inventory)
    current = 0

    with open(
        STATION_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.writer(file)

        writer.writerow(
            [
                "net",
                "kode_stasiun",
            ]
        )

        file.flush()

        for network in inventory:

            for station in network:

                current += 1

                network_code = network.code
                station_code = station.code

                print(
                    f"[{current}/{total}] "
                    f"{network_code}.{station_code}",
                    end=" ",
                )

                if not check_station(
                    network_code,
                    station_code,
                ):

                    print("-> Unauthorized")
                    continue

                writer.writerow(
                    [
                        network_code,
                        station_code,
                    ]
                )

                file.flush()

                print("✓ Saved")

    print()
    print("Finished.")


if __name__ == "__main__":
    generate_csv()