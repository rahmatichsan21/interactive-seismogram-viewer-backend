"""
Test: hourly cache — semua kasus.
Jalankan dari backend root.
"""
from datetime import datetime
from app.core.database import SessionLocal
from app.services.waveform_provider_service import get_waveform
from app.services.waveform_storage_service import (
    compute_hourly_windows,
    get_cached_channels_for_window,
    load_cached_window,
    run_waveform_cache_cleanup,
)
from app.core.config import CACHE_WINDOW_SECONDS

NET = "IA"
STA = "AAFM"
LOC = "*"
CHAN = "*"

db = SessionLocal()

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── Case A: Exact one-hour window ──
section("Case A: Exact one-hour window")
start = "2025-07-01T08:00:00"
end = "2025-07-01T09:00:00"

windows = compute_hourly_windows(
    datetime.fromisoformat(start),
    datetime.fromisoformat(end),
)
print(f"Windows: {[(w[0].isoformat(), w[1].isoformat()) for w in windows]}")
assert len(windows) == 1

# Clear cache first
import os, glob
from app.models.waveform import WaveformRecord
for f in glob.glob("storage/waveforms/*.mseed"):
    os.remove(f)
db.query(WaveformRecord).delete()
db.commit()

stream = get_waveform(db, NET, STA, LOC, CHAN, start, end)
print(f"First request - traces: {len(stream)}")
for tr in stream:
    print(f"  {tr.stats.station}.{tr.stats.channel} "
          f"{tr.stats.starttime} -> {tr.stats.endtime} "
          f"({tr.stats.npts} pts)")
assert len(stream) > 0

stream2 = get_waveform(db, NET, STA, LOC, CHAN, start, end)
print(f"Second request (CACHE HIT) - traces: {len(stream2)}")
assert len(stream2) == len(stream)
print("PASS")

# ── Case B: Cross-window request ──
section("Case B: Request crossing three windows")
start = "2025-07-01T08:45:00"
end = "2025-07-01T10:45:00"

windows = compute_hourly_windows(
    datetime.fromisoformat(start),
    datetime.fromisoformat(end),
)
print(f"Windows: {[(w[0].isoformat(), w[1].isoformat()) for w in windows]}")
assert len(windows) == 3

stream = get_waveform(db, NET, STA, LOC, CHAN, start, end)
print(f"Traces: {len(stream)}")
for tr in stream:
    print(f"  {tr.stats.station}.{tr.stats.channel} "
          f"{tr.stats.starttime} -> {tr.stats.endtime} "
          f"({tr.stats.npts} pts)")
    # Must be trimmed to exactly 08:45 -> 10:45
    assert tr.stats.starttime.strftime("%H:%M") == "08:45", \
        f"Expected 08:45, got {tr.stats.starttime}"
    assert tr.stats.endtime.strftime("%H:%M") == "10:45", \
        f"Expected 10:45, got {tr.stats.endtime}"
print("PASS (trimmed to 08:45–10:45)")

# ── Case D: Wildcard completeness ──
section("Case D: Wildcard channel completeness still works")
seen_channels = {tr.stats.channel for tr in stream}
print(f"Returned channels: {sorted(seen_channels)}")
cached_for_08 = get_cached_channels_for_window(
    db, NET, STA, LOC, CHAN,
    datetime(2025, 7, 1, 8, 0, 0),
    datetime(2025, 7, 1, 9, 0, 0),
)
print(f"Cached channels for 08-09: {sorted(cached_for_08)}")
assert seen_channels.issubset(cached_for_08), \
    f"Some returned channels not in cache: {seen_channels - cached_for_08}"
print("PASS (all returned channels are cached)")

# ── Case C: Delete a window, verify partial recovery ──
section("Case C: Partial cache — delete middle window")
win_start = datetime(2025, 7, 1, 9, 0, 0)
win_end = datetime(2025, 7, 1, 10, 0, 0)

cached = get_cached_channels_for_window(
    db, NET, STA, LOC, CHAN, win_start, win_end,
)
print(f"Channels cached for 09-10: {sorted(cached)}")

# Delete records and files for 09-10 window
records_for_window = (
    db.query(WaveformRecord)
    .filter(
        WaveformRecord.network == NET,
        WaveformRecord.station == STA,
        WaveformRecord.start_time == win_start,
        WaveformRecord.end_time == win_end,
    )
    .all()
)
for r in records_for_window:
    if os.path.exists(r.file_path):
        os.remove(r.file_path)
    db.delete(r)
db.commit()
print(f"Deleted {len(records_for_window)} records for 09-10 window")

stream = get_waveform(db, NET, STA, LOC, CHAN, start, end)
print(f"After partial recovery - traces: {len(stream)}")
recovered_channels = {tr.stats.channel for tr in stream}
print(f"Recovered channels: {sorted(recovered_channels)}")
assert len(stream) == 12, f"Expected 12 traces, got {len(stream)}"
print("PASS (middle window re-downloaded)")

# ── Case E: Cleanup ──
section("Case E: Cleanup — full hourly cache clear")
deleted_files, deleted_rows = run_waveform_cache_cleanup()
print(f"Deleted files: {deleted_files}")
print(f"Deleted database records: {deleted_rows}")
remaining_records = db.query(WaveformRecord).count()
print(f"Remaining records after cleanup: {remaining_records}")
assert remaining_records == 0, \
    "WaveformRecord harus kosong setelah full clear"
remaining_files = glob.glob("storage/waveforms/*.mseed")
print(f"Remaining files after cleanup: {len(remaining_files)}")
assert len(remaining_files) == 0, \
    "Tidak boleh ada .mseed tersisa setelah full clear"
print("PASS (full clear)")

db.close()
print(f"\n{'='*60}")
print("  ALL TESTS PASSED")
print(f"{'='*60}")
