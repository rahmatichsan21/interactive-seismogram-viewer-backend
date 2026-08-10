"""
Test: get_seen_channels() — cache sebagai source of truth untuk wildcard.
"""
import os, glob

from app.core.database import SessionLocal
from app.models.waveform import WaveformRecord
from app.services.waveform_provider_service import get_waveform
from app.services.waveform_storage_service import get_seen_channels

NET = "IA"
STA = "AAFM"
LOC = "*"
CHAN = "*"
START = "2025-07-01T08:00:00"
END = "2025-07-01T09:00:00"

db = SessionLocal()

# ── Bersihkan cache ──
for f in glob.glob("storage/waveforms/*.mseed"):
    os.remove(f)
db.query(WaveformRecord).delete()
db.commit()

seen = get_seen_channels(db, NET, STA)
print(f"[*] Seen channels (empty cache): {sorted(seen)}")
assert seen == set(), "Empty cache should produce empty seen set"

# ── Test 1: First wildcard request (cache empty) ──
print()
print("Test 1: First wildcard request (cache empty)")
stream = get_waveform(db, NET, STA, LOC, CHAN, START, END)
seen = get_seen_channels(db, NET, STA)
print(f"Traces returned : {len(stream)}")
print(f"Channels cached : {sorted(seen)}")
assert len(seen) > 0, "Seen channels should be populated after first download"
assert "VHE" not in seen, "VHE should NOT be in seen channels"
assert "VHN" not in seen, "VHN should NOT be in seen channels"
assert "VHZ" not in seen, "VHZ should NOT be in seen channels"
print("PASS (VHE/VHN/VHZ absent from cache)")

# ── Test 2: Second wildcard request (all cached) ──
print()
print("Test 2: Second wildcard request (should be CACHE HIT)")
stream2 = get_waveform(db, NET, STA, LOC, CHAN, START, END)
print(f"Traces returned : {len(stream2)}")
assert len(stream2) == len(stream), "Should get same number of traces"
print("PASS (cache hit — all deliverable channels cached)")

# ── Test 3: Non-wildcard still works ──
print()
print("Test 3: Non-wildcard SHZ")
stream3 = get_waveform(db, NET, STA, LOC, "SHZ", START, END)
print(f"Traces returned : {len(stream3)}")
assert len(stream3) == 1, "Single channel should return 1 trace"
assert stream3[0].stats.channel == "SHZ"
print("PASS (non-wildcard unaffected)")

# ── Test 4: VHE/VHN/VHZ NOT causing spurious downloads ──
print()
print("Test 4: No spurious downloads from inventory-metadata channels")
# Clear cache then simulate: first download populates seen channels
for f in glob.glob("storage/waveforms/*.mseed"):
    os.remove(f)
db.query(WaveformRecord).delete()
db.commit()

stream_first = get_waveform(db, NET, STA, LOC, CHAN, START, END)
first_seen = get_seen_channels(db, NET, STA)
print(f"First download — seen channels : {sorted(first_seen)}")
assert "VHE" not in first_seen

# Second request — should be CACHE HIT (no VHE/VHN/VHZ causing miss)
stream_second = get_waveform(db, NET, STA, LOC, CHAN, START, END)
second_seen = get_seen_channels(db, NET, STA)
print(f"Second request — seen channels: {sorted(second_seen)}")
assert second_seen == first_seen, "Seen channels should not change"
assert len(stream_second) == len(stream_first)
print("PASS (no spurious download from VHE/VHN/VHZ)")

db.close()
print(f"\n{'='*60}")
print("  ALL TESTS PASSED")
print(f"{'='*60}")
