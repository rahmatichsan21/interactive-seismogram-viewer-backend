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