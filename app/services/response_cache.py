import time
from collections import OrderedDict


class ResponseCache:
    """
    Response Cache — menyimpan Inventory FDSN `level="response"` untuk
    Instrument Correction.

    In-process memory (OrderedDict), bukan Redis/database — mengikuti
    pola ProcessingCache yang sudah ada.

    Key = (network, station, start_time, end_time) agar inventory dari
    station atau periode waktu berbeda tidak tertukar.

    TTL + LRU eviction (max_entries). Tanpa size guard per-entry untuk
    sekarang (inventory station umumnya kecil; max_entries cukup).
    """

    def __init__(self, ttl=300, max_entries=20):
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
response_cache = ResponseCache()