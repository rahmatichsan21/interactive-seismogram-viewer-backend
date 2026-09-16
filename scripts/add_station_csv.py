import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from obspy import UTCDateTime
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNUnauthorizedException,
    FDSNForbiddenException,
)

from app.core.config import (
    DEFAULT_NETWORK,
    STATION_CSV,
)

from app.core.fdsn_client import client

# Buffer setelah start_date operasional station, agar window
# pengecekan tidak jatuh tepat di hari instalasi (yang sering
# belum ada data karena baru dipasang).
CHECK_WINDOW_BUFFER_SECONDS = 86400  # 1 hari

# Panjang window pengecekan. Nilainya tidak memengaruhi hasil
# otorisasi (401/403 tidak bergantung isi data), hanya dipakai
# sebagai window valid untuk request get_waveforms().
CHECK_WINDOW_LENGTH_SECONDS = 60


def resolve_check_window(reference_start_date):
    """
    Tentukan window waktu HISTORIS (bukan real-time) untuk
    check_station(), berdasarkan tanggal mulai operasional
    station (metadata FDSN, mis. station.start_date).

    Sengaja tidak memakai UTCDateTime() (waktu sekarang) supaya
    pengecekan otorisasi tidak bergantung pada ketersediaan data
    real-time (yang bisa gagal karena telemetry delay, bukan
    karena benar-benar tidak diizinkan).

    Mengembalikan (start, end) atau (None, None) jika metadata
    start_date tidak tersedia.
    """

    if reference_start_date is None:
        return None, None

    start = UTCDateTime(reference_start_date) + CHECK_WINDOW_BUFFER_SECONDS
    end = start + CHECK_WINDOW_LENGTH_SECONDS

    return start, end


def check_station(network, station, start, end):
    """
    Cek apakah credential saat ini punya akses ke satu station,
    pada window (start, end) yang sudah ditentukan pemanggil
    (lihat resolve_check_window).

    Return value dibedakan 3 arti, JANGAN disederhanakan jadi
    True/False biner:
    - True  -> akses diizinkan (termasuk NoData/204, karena itu
               berarti credential diterima, hanya datanya kosong).
    - False -> BENAR-BENAR ditolak server (401 Unauthorized /
               403 Forbidden).
    - None  -> gagal teknis (timeout, koneksi, parsing, dll).
               INI BUKAN Unauthorized dan tidak boleh diperlakukan
               seperti itu oleh caller.
    """

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
        # Gagal teknis (timeout/koneksi/parsing/dll), BUKAN
        # penolakan akses. Jangan disamakan dengan Unauthorized.
        print(f"ERROR TEKNIS {network}.{station} : {error}")
        return None


def _read_existing_stations():
    """
    Baca STATION_CSV existing dan kembalikan set (net, kode_stasiun).
    Jika file belum ada, kembalikan set kosong.
    """

    existing = set()

    if not STATION_CSV.exists():
        return existing

    with open(
        STATION_CSV,
        "r",
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:
            existing.add(
                (row["net"], row["kode_stasiun"])
            )

    return existing


def add_single_station(network, station, existing):
    """
    Tambahkan SATU station ke STATION_CSV existing tanpa
    menghapus atau menimpa station lain.

    - Jika (network, station) sudah ada di `existing` -> SKIP,
      tidak menulis apa pun.
    - Jika belum ada -> ambil metadata station untuk dapat
      start_date, tentukan window historis (resolve_check_window),
      lalu jalankan check_station(). Jika hasilnya True, append
      satu baris. Jika False (Unauthorized/Forbidden) atau None
      (error teknis), tidak menulis apa pun.

    `existing` adalah set (network, station) yang sudah ada di
    CSV, dipakai bersama untuk banyak station dalam satu proses
    supaya tidak baca ulang file tiap station dan tidak membuat
    duplicate antar station yang diproses dalam batch yang sama.
    """

    if (network, station) in existing:
        print(
            f"{network}.{station} sudah ada di "
            f"{STATION_CSV}, tidak ada perubahan."
        )
        return

    print(f"{network}.{station}", end=" ")

    try:
        inventory = client.get_stations(
            network=network,
            station=station,
            level="station",
        )
        station_meta = inventory[0][0]
        reference_start_date = station_meta.start_date
    except Exception as error:
        print(
            f"-> Gagal mengambil metadata station ({error}), "
            "dilewati (perlu dicek ulang)"
        )
        return

    window_start, window_end = resolve_check_window(
        reference_start_date
    )

    if window_start is None:
        print(
            "-> Metadata start_date tidak tersedia, "
            "dilewati (perlu dicek manual)"
        )
        return

    result = check_station(network, station, window_start, window_end)

    if result is False:
        print("-> Unauthorized/Forbidden")
        return

    if result is None:
        print(
            "-> Dilewati (error teknis, bukan Unauthorized, "
            "perlu dicek ulang)"
        )
        return

    write_header = not STATION_CSV.exists()

    with open(
        STATION_CSV,
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.writer(file)

        if write_header:
            writer.writerow(
                [
                    "net",
                    "kode_stasiun",
                ]
            )

        writer.writerow(
            [
                network,
                station,
            ]
        )

        file.flush()

    print("✓ Saved")

    # Tandai sudah ada, supaya kalau station yang sama diulang
    # dalam --station yang sama (typo/duplikat input), tidak
    # ditambahkan dua kali.
    existing.add((network, station))


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Tambahkan satu atau lebih station ke stations.csv "
            "existing (tanpa regenerate/overwrite seluruh CSV)."
        )
    )

    parser.add_argument(
        "--station",
        required=True,
        nargs="+",
        help=(
            "Satu atau lebih kode station (dipisah spasi), "
            "mis. --station GTOI atau "
            "--station GTOI AAII PAGA KUKI. Tiap station dicek "
            "dan ditambahkan ke stations.csv existing secara "
            "independen."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    existing = _read_existing_stations()

    for station in args.station:
        add_single_station(DEFAULT_NETWORK, station, existing)