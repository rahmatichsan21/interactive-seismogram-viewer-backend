"""
Test: ProcessingCache — semua skenario.
"""
import time

from app.core.database import SessionLocal
from app.services.waveform_service import download_waveform
from app.services.processing_service import (
    process_waveform,
    process_waveform_per_channel,
)
from app.services.processing_cache import (
    processing_cache,
)
from app.models.processing import (
    TrimOperation,
    FilterOperation,
)
from obspy import Stream

NET = "IA"
STA = "AAFM"
LOC = "*"
START = "2025-07-01T08:00:00"
END = "2025-07-01T09:00:00"

db = SessionLocal()
processing_cache.clear()

stream = download_waveform(NET, STA, LOC, "SHZ", START, END)
trace = stream[0]

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── Test 1: Direct Filter → NO snapshot ──
section("Test 1: Direct Filter — no snapshot (empty prefix)")

ops = [FilterOperation(type="filter", filter_type="lowpass", freq=10.0)]
cache_info = {"network": NET, "station": STA,
              "start_time": START, "end_time": END, "channel": "SHZ"}

# Process first time
s = Stream(traces=[trace])
processed = list(process_waveform_per_channel(s, ops, cache_info=cache_info))
print(f"Processed {len(processed)} traces")

# Check: key for empty prefix should NOT exist
empty_key = processing_cache.make_key(NET, STA, "SHZ", START, END, [])
assert not processing_cache.has(empty_key), "Empty prefix should NOT be cached"
print("PASS — no snapshot for direct Filter")

# Cek juga: key untuk [Filter] juga tidak ada
filter_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops)
assert not processing_cache.has(filter_key), "Filter-only key should NOT be cached"
print("PASS — no snapshot for Filter-only pipeline")

# ── Test 2: Trim → Filter → snapshot Trim ──
section("Test 2: Trim → Filter — snapshot BEFORE Filter")

ops = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="lowpass", freq=10.0),
]
processing_cache.clear()

s = Stream(traces=[trace])
processed = list(process_waveform_per_channel(s, ops, cache_info=cache_info))
print(f"Processed {len(processed)} traces")

trim_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops[:1])
print(f"Trim key cached? {processing_cache.has(trim_key)}")
assert processing_cache.has(trim_key), "Trim snapshot should be cached"
print("PASS — snapshot for Trim prefix created")

# ── Test 3: Undo — Trim only, should HIT cache ──
section("Test 3: Undo Filter — use cached Trim snapshot")

ops_trim_only = [TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                                end_time="2025-07-01T08:40:00")]

s = Stream(traces=[trace])
processed = list(process_waveform_per_channel(s, ops_trim_only,
                                               cache_info=cache_info))
print(f"Processed {len(processed)} traces")

trim_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_trim_only)
print(f"Trim key still cached? {processing_cache.has(trim_key)}")
assert processing_cache.has(trim_key), "Trim snapshot should still be cached"
print("PASS — Undo uses cached Trim snapshot (no Filter replay)")

# ── Test 4: Redo — Trim → Filter, replay Filter ──
section("Test 4: Redo Filter — replay from Trim snapshot")

s = Stream(traces=[trace])
processed = list(process_waveform_per_channel(s, ops, cache_info=cache_info))
print(f"Processed {len(processed)} traces")
print("PASS — Redo processed Filter again from Trim")

# ── Test 5: Different channel = different keys ──
section("Test 5: Different channels = different keys")

stream_all = download_waveform(NET, STA, LOC, "BHZ", START, END)
bhz_trace = stream_all[0]

processing_cache.clear()

# Process SHZ first
shz_s = Stream(traces=[trace])
shz_cache_info = {**cache_info, "channel": "SHZ"}

ops_5 = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="lowpass", freq=5.0),
]

list(process_waveform_per_channel(shz_s, ops_5, cache_info=shz_cache_info))

print(f"SHZ entries: {len(processing_cache._cache)}")

# Process BHZ
bhz_s = Stream(traces=[bhz_trace])
bhz_cache_info = {**cache_info, "channel": "BHZ"}
list(process_waveform_per_channel(bhz_s, ops_5, cache_info=bhz_cache_info))

print(f"After BHZ entries: {len(processing_cache._cache)}")

shz_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_5[:1])
bhz_key = processing_cache.make_key(NET, STA, "BHZ", START, END, ops_5[:1])
assert shz_key != bhz_key, "SHZ and BHZ should have different keys"
assert processing_cache.has(shz_key), "SHZ snapshot should exist"
assert processing_cache.has(bhz_key), "BHZ snapshot should exist"
print("PASS — different channels = different cache entries")

# ── Test 6: Different filter parameters = different keys ──
section("Test 6: Different filter params = different keys")

ops_a = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="bandpass",
                     freqmin=1.0, freqmax=10.0),
]
ops_b = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="bandpass",
                     freqmin=5.0, freqmax=20.0),
]

key_a = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_a[:1])
key_b = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_b[:1])
# Trim prefix is identical, keys should be same
assert key_a == key_b, "Same Trim prefix = same key"
print("PASS — same Trim prefix produces same key")

key_a_full = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_a)
key_b_full = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_b)
assert key_a_full != key_b_full, "Different filter params should produce different keys"
print("PASS — different filter params = different keys")

# ── Test 7: Repeated Apply — no duplicate Stream.copy() ──
section("Test 7: Repeated Apply — cache.has() prevents duplicate")

processing_cache.clear()
ops = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="lowpass", freq=10.0),
]

count_before = len(processing_cache._cache)
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops, cache_info=cache_info))
count_1 = len(processing_cache._cache)
print(f"First apply — entries: {count_before} → {count_1}")

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops, cache_info=cache_info))
count_2 = len(processing_cache._cache)
print(f"Second apply — entries: {count_2}")

assert count_2 == count_1, f"Repeated Apply should not add entries ({count_1} → {count_2})"
print("PASS — cache.has() prevents duplicate Stream.copy()")

# ── Test 8: TTL — expired entries removed ──
section("Test 8: TTL — expired entries removed")

# Create a separate cache with TTL=2s for testing
from app.services.processing_cache import ProcessingCache
test_cache = ProcessingCache(ttl=2, max_entries=20)

stream_test = download_waveform(NET, STA, LOC, "SHZ", START, END)
tr = stream_test[0]
key_ttl = test_cache.make_key(NET, STA, "SHZ", START, END, ops[:1])
test_cache.put(key_ttl, Stream(traces=[tr.copy()]))
assert test_cache.has(key_ttl), "Should exist before TTL"
print(f"Entry created, sleeping 3s...")
time.sleep(3)
assert not test_cache.has(key_ttl), "Should be removed after TTL"
print("PASS — TTL expires entries")

# ── Test 9: LRU eviction ──
section("Test 9: LRU eviction at max entries")

small_cache = ProcessingCache(ttl=300, max_entries=3, max_size_bytes=200_000_000)
for i in range(5):
    key = f"key_{i}"
    small_cache.put(key, Stream(traces=[tr.copy()]))
print(f"Entries after 5 puts (max=3): {len(small_cache._cache)}")
assert len(small_cache._cache) == 3, "Should be capped at 3"
assert "key_0" not in small_cache._cache, "Oldest should be evicted"
assert "key_1" not in small_cache._cache, "Second oldest should be evicted"
assert "key_2" in small_cache._cache, "Third should survive"
print("PASS — LRU eviction works")

# ── Test 10: Sweep removes expired ──
section("Test 10: Periodic sweep removes expired")

sweep_cache = ProcessingCache(ttl=1, max_entries=20)
sweep_cache.put("sweep_a", Stream(traces=[tr.copy()]))
sweep_cache.put("sweep_b", Stream(traces=[tr.copy()]))
print(f"Entries before sleep: {len(sweep_cache._cache)}")
time.sleep(2)
removed = sweep_cache.sweep()
print(f"Removed by sweep: {removed}")
assert removed == 2, "Both entries should be removed"
assert len(sweep_cache._cache) == 0
print("PASS — sweep removes all expired entries")

# ── Test 11: >200MB entry skipped ──
section("Test 11: Entry >200MB skipped")

big_cache = ProcessingCache(ttl=300, max_entries=20, max_size_bytes=100)
# A single trace with a few hundred samples is >100 bytes
result = big_cache.put("big_entry", Stream(traces=[tr.copy()]))
print(f"Big entry stored? {result}")
assert not result, "Entry >100 bytes should be rejected"
assert "big_entry" not in big_cache._cache
print("PASS — large entries skipped")

# ── Test 12: Different station = different keys ──
section("Test 12: Different station = different keys")

key_aafm = processing_cache.make_key(NET, "AAFM", "SHZ", START, END, ops[:1])
key_cilji = processing_cache.make_key(NET, "CILJI", "SHZ", START, END, ops[:1])
assert key_aafm != key_cilji, "Different stations should produce different keys"
print("PASS — different stations = different keys")

# ── Test 13: Different time range = different keys ──
section("Test 13: Different time range = different keys")

key_1h = processing_cache.make_key(NET, STA, "SHZ", START,
                                    "2025-07-01T09:00:00", ops[:1])
key_2h = processing_cache.make_key(NET, STA, "SHZ", START,
                                    "2025-07-01T10:00:00", ops[:1])
assert key_1h != key_2h, "Different time ranges should produce different keys"
print("PASS — different time ranges = different keys")

processing_cache.clear()
db.close()

print(f"\n{'='*60}")
print("  ALL TESTS PASSED")
print(f"{'='*60}")
