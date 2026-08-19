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

# Ukuran satu jendela cache waveform dalam detik.
# Waveform disimpan dalam jendela UTC-aligned dengan
# lebar CACHE_WINDOW_SECONDS, bukan berdasarkan rentang
# request user. Contoh: 3600 = 1 jam.
CACHE_WINDOW_SECONDS = int(
    os.getenv("CACHE_WINDOW_SECONDS")
)

# Waktu harian pembersihan SELURUH Hourly Waveform Cache
# (format HH:MM, 24-jam). Contoh: "00:00" = tengah malam,
# "02:30" = jam 02:30. Konsep retention (umur file) sudah
# dihapus — cache dibersihkan menyeluruh setiap hari pada
# waktu ini. Wajib dikonfigurasi di .env; config.py membaca
# dan memvalidasi, tidak menyediakan fallback.
def _parse_hourly_cache_clear_time(value):
    if not value:
        raise ValueError(
            "HOURLY_CACHE_CLEAR_TIME wajib dikonfigurasi "
            "di .env dengan format HH:MM (contoh: 00:00)."
        )
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(
            "HOURLY_CACHE_CLEAR_TIME harus berformat HH:MM, "
            f"ditemukan: {value!r}"
        )
    hour, minute = parts
    if len(hour) != 2 or len(minute) != 2:
        raise ValueError(
            "HOURLY_CACHE_CLEAR_TIME harus berformat HH:MM "
            f"dengan dua digit (contoh: 00:00), ditemukan: {value!r}"
        )
    try:
        hour = int(hour)
        minute = int(minute)
    except ValueError:
        raise ValueError(
            "HOURLY_CACHE_CLEAR_TIME harus berisi angka "
            f"HH:MM, ditemukan: {value!r}"
        ) from None
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ValueError(
            "HOURLY_CACHE_CLEAR_TIME di luar rentang "
            f"00:00–23:59, ditemukan: {value!r}"
        )
    return f"{hour:02d}:{minute:02d}"


HOURLY_CACHE_CLEAR_TIME = _parse_hourly_cache_clear_time(
    os.getenv("HOURLY_CACHE_CLEAR_TIME")
)
