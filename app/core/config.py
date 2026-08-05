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

# Hard Limit (proteksi RAM) - lihat app/routers/processing.py.
# Sengaja MAX per-channel, BUKAN total semua channel dijumlah -
# sejak processing direfaktor jadi Sequential Per-Channel,
# siklus hidup memori yang mahal (copy berlapis + filtfilt) itu
# per-channel, jadi limitnya harus merefleksikan channel
# TERBESAR yang akan diproses, bukan jumlah semuanya.
MAX_POINTS_PER_CHANNEL_LIMIT = int(
    os.getenv("MAX_POINTS_PER_CHANNEL_LIMIT", "15000000")
)

# TTL cache metadata channel (level="channel") di
# inventory_service.py. Channel list & sampling_rate suatu
# station nyaris tidak pernah berubah (cuma saat upgrade
# instrumen), jadi TTL panjang aman.
INVENTORY_CACHE_TTL_SECONDS = int(
    os.getenv("INVENTORY_CACHE_TTL_SECONDS", "3600")
)