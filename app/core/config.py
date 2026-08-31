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


# --- Konfigurasi operasional (dapat di-tuning via .env) ---
# Nilai default di sini mencerminkan behavior existing; .env boleh
# menimpanya. Jangan ubah CACHE_WINDOW_SECONDS / HOURLY_CACHE_CLEAR_TIME.

# Timeout request FDSN/BMKG dalam detik.
FDSN_TIMEOUT_SECONDS = int(os.getenv("FDSN_TIMEOUT_SECONDS", "20"))

# Retry download waveform (total percobaan & delay antar percobaan).
MAX_DOWNLOAD_ATTEMPTS = int(os.getenv("MAX_DOWNLOAD_ATTEMPTS", "3"))
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "2"))

# ProcessingCache (L1 hasil processing): TTL, jumlah entry, batas ukuran.
PROCESSING_CACHE_TTL_SECONDS = int(
    os.getenv("PROCESSING_CACHE_TTL_SECONDS", "300")
)
PROCESSING_CACHE_MAX_ENTRIES = int(
    os.getenv("PROCESSING_CACHE_MAX_ENTRIES", "20")
)
PROCESSING_CACHE_MAX_SIZE_BYTES = int(
    os.getenv("PROCESSING_CACHE_MAX_SIZE_BYTES", "200000000")
)

# Instrument Response L1 cache (in-memory Inventory): TTL & jumlah entry.
RESPONSE_CACHE_TTL_SECONDS = int(
    os.getenv("RESPONSE_CACHE_TTL_SECONDS", "300")
)
RESPONSE_CACHE_MAX_ENTRIES = int(
    os.getenv("RESPONSE_CACHE_MAX_ENTRIES", "20")
)

# Interval sweep ProcessingCache (detik) & backoff cleanup error (detik).
PROCESSING_SWEEP_INTERVAL_SECONDS = int(
    os.getenv("PROCESSING_SWEEP_INTERVAL_SECONDS", "60")
)
CACHE_CLEANUP_RETRY_SECONDS = int(
    os.getenv("CACHE_CLEANUP_RETRY_SECONDS", "3600")
)

# Panjang segmen PSD (detik) utk ObsPy PPSD. Waveform lebih pendek
# dari nilai ini akan ditolak (error jelas). Developer dapat
# menyesuaikan via .env.
PPSD_LENGTH_SECONDS = int(os.getenv("PPSD_LENGTH_SECONDS", "300"))

# Overlap segmen PSD (0..1) utk ObsPy PPSD. Memengaruhi hasil PSD;
# default sama persis dengan behavior saat ini.
PPSD_OVERLAP = float(os.getenv("PPSD_OVERLAP", "0.5"))

# Cache hasil PSD (RAM-only, ephemeral).
PSD_CACHE_TTL_SECONDS = int(os.getenv("PSD_CACHE_TTL_SECONDS", "300"))
PSD_CACHE_MAX_ENTRIES = int(os.getenv("PSD_CACHE_MAX_ENTRIES", "20"))

# Cache hasil Spectrogram (RAM-only, ephemeral).
SPECTROGRAM_CACHE_TTL_SECONDS = int(
    os.getenv("SPECTROGRAM_CACHE_TTL_SECONDS", "300")
)
SPECTROGRAM_CACHE_MAX_ENTRIES = int(
    os.getenv("SPECTROGRAM_CACHE_MAX_ENTRIES", "20")
)
