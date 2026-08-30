import hashlib
import time
from collections import OrderedDict

from obspy import Stream

from app.core.config import (
    PROCESSING_CACHE_TTL_SECONDS,
    PROCESSING_CACHE_MAX_ENTRIES,
    PROCESSING_CACHE_MAX_SIZE_BYTES,
)


def _serialize_operation(operation):
    """Serialize satu operation menjadi string pendek untuk cache key."""
    if operation.type == "trim":
        return (
            f"trim:start={operation.start_time},"
            f"end={operation.end_time}"
        )
    if operation.type == "filter":
        parts = [f"filter:{operation.filter_type}"]
        if operation.filter_type in ("lowpass", "highpass"):
            parts.append(f"freq={operation.freq}")
        elif operation.filter_type == "bandpass":
            parts.append(
                f"freqmin={operation.freqmin},"
                f"freqmax={operation.freqmax}"
            )
        parts.append(
            f"corners={operation.corners},"
            f"zerophase={operation.zerophase}"
        )
        return ":".join(parts)
    if operation.type == "instrument_correction":
        pre_filt = (
            ",".join(str(v) for v in operation.pre_filt)
            if operation.pre_filt is not None
            else "none"
        )
        return (
            f"instrument_correction:output={operation.output},"
            f"pre_filt={pre_filt},"
            f"water_level={operation.water_level}"
        )
    return operation.type


class ProcessingCache:
    """
    Temporary Processing Cache — menyimpan snapshot
    full-resolution ObsPy Stream SEBELUM operation mahal
    (Filter, Instrument Correction).

    In-process memory (OrderedDict), bukan Redis.
    TTL + LRU + batas ukuran entry.
    """

    def __init__(
        self,
        ttl=PROCESSING_CACHE_TTL_SECONDS,
        max_entries=PROCESSING_CACHE_MAX_ENTRIES,
        max_size_bytes=PROCESSING_CACHE_MAX_SIZE_BYTES,
    ):
        self._cache = OrderedDict()
        self._ttl = ttl
        self._max_entries = max_entries
        self._max_size_bytes = max_size_bytes

    @staticmethod
    def make_key(
        network,
        station,
        channel,
        start_time,
        end_time,
        operations,
    ):
        raw = "|".join([
            network,
            station,
            channel,
            start_time,
            end_time,
            "|".join(
                _serialize_operation(op) for op in operations
            ),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def has(self, key):
        if key not in self._cache:
            return False
        entry = self._cache[key]
        if time.time() - entry["created_at"] > self._ttl:
            del self._cache[key]
            return False
        self._cache.move_to_end(key)
        return True

    def get(self, key):
        if not self.has(key):
            return None
        return self._cache[key]["stream"]

    def put(self, key, stream):
        if self.has(key):
            return True

        size = sum(trace.data.nbytes for trace in stream)
        if size > self._max_size_bytes:
            return False

        while len(self._cache) >= self._max_entries:
            self._cache.popitem(last=False)

        self._cache[key] = {
            "stream": stream,
            "created_at": time.time(),
        }
        self._cache.move_to_end(key)
        return True

    def sweep(self):
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


# Singleton — satu instance untuk seluruh backend.
# Parameter TTL/entries/ukuran diambil dari config (dapat di-tuning).
processing_cache = ProcessingCache(
    ttl=PROCESSING_CACHE_TTL_SECONDS,
    max_entries=PROCESSING_CACHE_MAX_ENTRIES,
    max_size_bytes=PROCESSING_CACHE_MAX_SIZE_BYTES,
)
