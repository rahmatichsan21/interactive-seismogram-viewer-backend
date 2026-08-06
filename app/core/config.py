import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "data"

STATION_CSV = DATA_DIR / "stations.csv"

BMKG_URL = os.getenv("BMKG_URL")
BMKG_USERNAME = os.getenv("BMKG_USERNAME")
BMKG_PASSWORD = os.getenv("BMKG_PASSWORD")
DEFAULT_NETWORK = "IA"

# Durasi (detik) yang menentukan KAPAN Time Bucket (envelope
# min/max) mulai aktif. Threshold efektif dihitung per trace:
# DECIMATION_DURATION_SECONDS * trace.stats.sampling_rate.
# Berbasis durasi (bukan jumlah sampel mentah) supaya pengalaman
# konsisten lintas channel - semua channel (1/20/50/100 Hz)
# mulai men-decimate pada durasi yang sama, bukan pada jumlah
# titik yang berbeda-beda. Default 3600 detik = 1 jam.
DECIMATION_DURATION_SECONDS = int(
    os.getenv("DECIMATION_DURATION_SECONDS", "999999")
)