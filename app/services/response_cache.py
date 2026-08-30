import time
from collections import OrderedDict

from app.core.config import (
    RESPONSE_CACHE_TTL_SECONDS,
    RESPONSE_CACHE_MAX_ENTRIES,
)


class ResponseCache:
    """
    Response Cache — menyimpan Inventory FDSN `level="response"` untuk
    Instrument Correction.

    In-process memory (OrderedDict), bukan Redis/database — mengikuti
    pola ProcessingCache yang sudah ada.

    Key = (network, station) — satu Inventory per station (semua channel
    & epoch). Sama dengan key persistent L2. start/end waktu tidak masuk
    key karena `inventory.get_response(seed_id, time)` memilih response
    yang benar berdasarkan channel + waktu.

    TTL + LRU eviction (max_entries). Tanpa size guard per-entry untuk
    sekarang (inventory station umumnya kecil; max_entries cukup).
    """

    def __init__(self, ttl=RESPONSE_CACHE_TTL_SECONDS, max_entries=RESPONSE_CACHE_MAX_ENTRIES):
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
        return entry["inventory"]

    def put(self, key, inventory):
        if key in self._cache:
            # Refresh timestamp (hapus lalu tulis ulang).
            del self._cache[key]

        while len(self._cache) >= self._max_entries:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "inventory": inventory,
            "created_at": time.time(),
        }
        self._cache.move_to_end(key)

    def has(self, key):
        return self.get(key) is not None

    def clear(self):
        self._cache.clear()


# Singleton — satu instance untuk seluruh backend.
# TTL/max_entries diambil dari config (dapat di-tuning).
response_cache = ResponseCache(
    ttl=RESPONSE_CACHE_TTL_SECONDS,
    max_entries=RESPONSE_CACHE_MAX_ENTRIES,
)