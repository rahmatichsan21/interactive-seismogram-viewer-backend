from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR.parent / "data"

STATION_CSV = DATA_DIR / "stations.csv"

BMKG_URL = "https://geof.bmkg.go.id"

BMKG_USERNAME = "bmkg"
BMKG_PASSWORD = "inatews2303#!3"