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

# Batas jumlah raw point per trace SEBELUM Time Bucket
# (temporal-order min/max decimation) mulai aktif.
# Trigger: raw_point_count > MAX_DISPLAY_POINTS.
# Sekaligus menentukan target output: target_buckets =
# MAX_DISPLAY_POINTS // 2, sehingga output akhir ≈
# MAX_DISPLAY_POINTS titik (2 per bucket dari temporal-order).
# Wajib dikonfigurasi di .env; config.py hanya membaca,
# tidak menyediakan fallback.
MAX_DISPLAY_POINTS = int(
    os.getenv("MAX_DISPLAY_POINTS")
)