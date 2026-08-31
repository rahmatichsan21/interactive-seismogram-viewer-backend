import hashlib
import logging
import time
from collections import OrderedDict

from app.core.config import (
    PSD_CACHE_TTL_SECONDS,
    PSD_CACHE_MAX_ENTRIES,
    SPECTROGRAM_CACHE_TTL_SECONDS,
    SPECTROGRAM_CACHE_MAX_ENTRIES,
)

logger = logging.getLogger(__name__)


def make_cache_key(*parts):
    """
    Cache key dari identity lengkap (network, station, location, channel,
    waktu, dll). Semua bagian yang None dinormalisasi ke "". Menggunakan
    sha256 agar aman dari karakter aneh.
    """
    raw = "|".join(
        "" if p is None else str(p) for p in parts
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TTLCache:
    """
    RAM-only TTL/LRU cache generic (pola ProcessingCache):
    - OrderedDict + TTL lazy + max_entries LRU.
    - Hilang saat backend restart; tidak disimpan ke disk.
    - Entry: {"value": <objek>, "created_at": <ts>}.
    """

    def __init__(self, ttl, max_entries):
        self._cache = OrderedDict()
        self._ttl = ttl
        self._max_entries = max_entries

    def get(self, key):
        entry = self._cache.get(key)

        if entry is None:
            return None

        if time.time() - entry["created_at"] > self._ttl:
            del self._cache[key]
            return None

        self._cache.move_to_end(key)
        return entry["value"]

    def put(self, key, value):
        if key in self._cache:
            # Refresh timestamp.
            del self._cache[key]

        while len(self._cache) >= self._max_entries:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "value": value,
            "created_at": time.time(),
        }
        self._cache.move_to_end(key)

    def has(self, key):
        return self.get(key) is not None

    def sweep(self):
        """Hapus semua entry yang expired; return jumlah yang dihapus."""
        now = time.time()
        expired = [
            k
            for k, v in self._cache.items()
            if now - v["created_at"] > self._ttl
        ]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def clear(self):
        self._cache.clear()


# Singleton — satu instance per fitur, konfigurasi dari .env.
psd_cache = TTLCache(
    ttl=PSD_CACHE_TTL_SECONDS,
    max_entries=PSD_CACHE_MAX_ENTRIES,
)
spectrogram_cache = TTLCache(
    ttl=SPECTROGRAM_CACHE_TTL_SECONDS,
    max_entries=SPECTROGRAM_CACHE_MAX_ENTRIES,
)