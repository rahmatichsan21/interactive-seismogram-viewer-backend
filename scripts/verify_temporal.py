from app.services.waveform_service import download_waveform, trace_to_json
from app.core.config import MAX_DISPLAY_POINTS

NETWORK = "IA"
STATION = "AAFM"
LOCATION = "*"
CHANNEL = "SHZ"
MAX_POINTS_BUCKETS = MAX_DISPLAY_POINTS // 2

print(f"MAX_DISPLAY_POINTS   = {MAX_DISPLAY_POINTS}")
print(f"MAX_POINTS (buckets)  = {MAX_POINTS_BUCKETS}")

print()
print("=== Test 1: Below threshold (5 min) ===")
stream = download_waveform(
    network=NETWORK, station=STATION, location=LOCATION,
    channel=CHANNEL,
    start_time="2025-07-01T00:00:00", end_time="2025-07-01T00:05:00",
)
trace = stream[0]
result = trace_to_json(trace, max_points=MAX_POINTS_BUCKETS)
print(f"raw_point_count     : {result['raw_point_count']}")
print(f"decimated           : {result['decimated']}")
assert result["raw_point_count"] <= MAX_DISPLAY_POINTS, "Should be below threshold"
assert result["decimated"] is False, "Should NOT be decimated"
print("PASS")

print()
print("=== Test 2: Above threshold (4h) ===")
stream = download_waveform(
    network=NETWORK, station=STATION, location=LOCATION,
    channel=CHANNEL,
    start_time="2025-07-01T00:00:00", end_time="2025-07-01T04:00:00",
)
trace = stream[0]
result = trace_to_json(trace, max_points=MAX_POINTS_BUCKETS)
print(f"raw_point_count     : {result['raw_point_count']}")
print(f"decimated           : {result['decimated']}")
print(f"returned_point_count: {result['returned_point_count']}")
print(f"amplitude length    : {len(result['amplitude'])}")
assert result["raw_point_count"] > MAX_DISPLAY_POINTS, "Should be above threshold"
assert result["decimated"] is True, "Should be decimated"
assert result["returned_point_count"] < result["raw_point_count"]
# Output harus sekitar MAX_DISPLAY_POINTS (bukan ~4000)
assert result["returned_point_count"] > 100000, (
    f"Expected ~{MAX_DISPLAY_POINTS} points, got {result['returned_point_count']}"
)
print(f"Within ~{MAX_DISPLAY_POINTS}: PASS")
print("PASS")

print()
print("=== All tests passed ===")
