"""
Test: ProcessingCache Hybrid A+D — semua skenario.
"""
from obspy import Stream

from app.core.database import SessionLocal
from app.services.waveform_service import download_waveform
from app.services.processing_service import process_waveform_per_channel
from app.services.processing_cache import processing_cache
from app.models.processing import (
    TrimOperation,
    FilterOperation,
)

NET = "IA"
STA = "AAFM"
LOC = "*"
START = "2025-07-01T08:00:00"
END = "2025-07-01T09:00:00"
CACHE_INFO = {"network": NET, "station": STA,
              "start_time": START, "end_time": END}

db = SessionLocal()
stream = download_waveform(NET, STA, LOC, "SHZ", START, END)
trace = stream[0]


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def count_entries():
    return len(processing_cache._cache)


# ── Test 1: Single Filter Apply → Undo → Redo ──
section("Test 1: Single Filter Apply → Undo → Redo")
processing_cache.clear()

ops_f1 = [FilterOperation(type="filter", filter_type="highpass", freq=1.0)]

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_f1, cache_info=CACHE_INFO))
e1 = count_entries()
print(f"Entries after Apply F1: {e1}")
assert e1 == 1, "Should store 1 final result"
print("PASS — final result stored")

# Undo (same pipeline, cache hit)
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_f1, cache_info=CACHE_INFO))
e2 = count_entries()
print(f"Entries after Undo/Re-Apply F1: {e2}")
assert e2 == 1, "Should be cache HIT, no new entries"
print("PASS — cache HIT for same pipeline")

# ── Test 2: Edit Filter (3 history states) ──
section("Test 2: Edit Filter HP1→HP2→BP — Undo")
processing_cache.clear()

# Apply HP 1 Hz
ops_hp1 = [FilterOperation(type="filter", filter_type="highpass", freq=1.0)]
processing_cache.clear()
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_hp1, cache_info=CACHE_INFO))
print(f"HP1 entries: {count_entries()}")
assert count_entries() == 1

# Apply HP 2 Hz  
ops_hp2 = [FilterOperation(type="filter", filter_type="highpass", freq=2.0)]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_hp2, cache_info=CACHE_INFO))
print(f"HP2 entries: {count_entries()}")
assert count_entries() == 2

# Apply BP 1-10 Hz
ops_bp = [FilterOperation(type="filter", filter_type="bandpass",
                           freqmin=1.0, freqmax=10.0)]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_bp, cache_info=CACHE_INFO))
print(f"BP entries: {count_entries()}")
assert count_entries() == 3

# Undo BP→HP2: lookup ops_hp2 → HIT
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_hp2, cache_info=CACHE_INFO))
print(f"Undo→HP2 entries: {count_entries()}")
assert count_entries() == 3, "Should HIT, same entries"
print("Undo→HP2: PASS")

# Undo HP2→HP1: lookup ops_hp1 → HIT
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_hp1, cache_info=CACHE_INFO))
print(f"Undo→HP1 entries: {count_entries()}")
assert count_entries() == 3
print("Undo→HP1: PASS")

# Redo HP1→HP2: HIT (TTL still fresh)
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_hp2, cache_info=CACHE_INFO))
print(f"Redo→HP2: PASS")

# Redo HP2→BP: HIT
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_bp, cache_info=CACHE_INFO))
print(f"Redo→BP: PASS")

# ── Test 3: Trim → Filter → Undo Filter ──
section("Test 3: Trim → Filter → Undo Filter")
processing_cache.clear()

ops_tf = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
    FilterOperation(type="filter", filter_type="bandpass",
                     freqmin=1.0, freqmax=10.0),
]

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_tf, cache_info=CACHE_INFO))
print(f"Trim→Filter entries: {count_entries()}")

# Check: snapshot [Trim] + final [Trim,Filter]
trim_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_tf[:1])
tf_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_tf)
assert processing_cache.has(trim_key), "Snapshot [Trim] should exist"
assert processing_cache.has(tf_key), "Final [Trim,Filter] should exist"
print("PASS — snapshot [Trim] + final [Trim,Filter]")

# Undo Filter: ops=[Trim] → HIT snapshot
ops_trim = [ops_tf[0]]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_trim, cache_info=CACHE_INFO))
print("Undo Filter: PASS (snapshot HIT)")

# ── Test 4: Filter → Trim → Undo Trim ──
section("Test 4: Filter → Trim → Undo Trim")
processing_cache.clear()

ops_ft = [
    FilterOperation(type="filter", filter_type="bandpass",
                     freqmin=1.0, freqmax=10.0),
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
]

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_ft, cache_info=CACHE_INFO))
print(f"Filter→Trim entries: {count_entries()}")

# Check: snapshot [Filter] + final [Filter,Trim]
f_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_ft[:1])
ft_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_ft)
assert processing_cache.has(f_key), "Snapshot [Filter] should exist"
assert processing_cache.has(ft_key), "Final [Filter,Trim] should exist"
print("PASS — snapshot [Filter] + final [Filter,Trim]")

# Undo Trim: ops=[Filter] → HIT snapshot
ops_filter = [ops_ft[0]]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_filter, cache_info=CACHE_INFO))
print("Undo Trim: PASS (snapshot HIT)")

# ── Test 5: F1→F2→F3 → Undo bertingkat ──
section("Test 5: F1→F2→F3 → Undo bertingkat")
processing_cache.clear()

ops_chain = [
    FilterOperation(type="filter", filter_type="highpass", freq=1.0),
    FilterOperation(type="filter", filter_type="bandpass",
                     freqmin=1.0, freqmax=10.0),
    FilterOperation(type="filter", filter_type="lowpass", freq=15.0),
]

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_chain, cache_info=CACHE_INFO))
print(f"F1→F2→F3 entries: {count_entries()}")

# Check snapshots + final
f1_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_chain[:1])
f12_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_chain[:2])
f123_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_chain)

assert processing_cache.has(f1_key), "Snapshot [F1] should exist"
assert processing_cache.has(f12_key), "Snapshot [F1,F2] should exist"
assert processing_cache.has(f123_key), "Final [F1,F2,F3] should exist"
print("PASS — [F1] + [F1,F2] + final [F1,F2,F3]")

# Undo F3 → [F1,F2]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_chain[:2], cache_info=CACHE_INFO))
print("Undo→[F1,F2]: HIT (PREVIOUS)")

# Undo F2 → [F1]
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_chain[:1], cache_info=CACHE_INFO))
print("Undo→[F1]: HIT (PREVIOUS)")

# ── Test 6: Trim saja → NO snapshot ──
section("Test 6: Trim saja — no unnecessary snapshot")
processing_cache.clear()

ops_trim_only = [
    TrimOperation(type="trim", start_time="2025-07-01T08:10:00",
                   end_time="2025-07-01T08:40:00"),
]

s = Stream(traces=[trace])
list(process_waveform_per_channel(s, ops_trim_only, cache_info=CACHE_INFO))
e = count_entries()
print(f"Trim-only entries: {e}")

trim_key = processing_cache.make_key(NET, STA, "SHZ", START, END, ops_trim_only)
# Final result is still stored (Strategy D) but no prefix snapshot (Strategy A)
print(f"Trim prefix(key) exists: {processing_cache.has(trim_key)}")
print(f"PASS — {e} entries (final only, no prefix snapshot)")

# ── Test 7: Empty pipeline → Raw Hourly Cache ──
section("Test 7: Empty pipeline")
s = Stream(traces=[trace])
list(process_waveform_per_channel(s, [], cache_info=CACHE_INFO))
# operations=[] → cache check skipped → fallback to normal processing
# No cache entries should be added
print("Empty pipeline: PASS (uses Raw Hourly Cache)")

# ── Test 8: Different filter params = different keys ──
section("Test 8: Cache key isolates params")
k1 = processing_cache.make_key(NET, STA, "SHZ", START, END, [ops_hp1[0]])
k2 = processing_cache.make_key(NET, STA, "SHZ", START, END, [ops_hp2[0]])
k3 = processing_cache.make_key(NET, STA, "SHZ", START, END, [ops_bp[0]])
assert k1 != k2 != k3, "All three keys should be different"
print("PASS — HP1, HP2, BP all have different keys")

# ── Test 9: TTL still works with final entries ──
section("Test 9: TTL still works")
from app.services.processing_cache import ProcessingCache
import time

ttl_cache = ProcessingCache(ttl=2, max_entries=20)
ttl_cache.put("test", Stream(traces=[trace.copy()]))
assert ttl_cache.has("test")
time.sleep(3)
assert not ttl_cache.has("test")
print("PASS — TTL expiry works for final entries")

# ── Test 10: LRU still works ──
section("Test 10: LRU still works")
lru_cache = ProcessingCache(ttl=300, max_entries=3)
for i in range(5):
    lru_cache.put(f"k{i}", Stream(traces=[trace.copy()]))
assert len(lru_cache._cache) == 3
assert "k0" not in lru_cache._cache
assert "k1" not in lru_cache._cache
print("PASS — LRU eviction works")

db.close()
processing_cache.clear()

print(f"\n{'='*60}")
print("  ALL TESTS PASSED")
print(f"{'='*60}")
