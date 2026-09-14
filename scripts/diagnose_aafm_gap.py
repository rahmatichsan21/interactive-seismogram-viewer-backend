from datetime import datetime

import numpy as np
from obspy import Stream

from app.core.database import SessionLocal
from app.services.waveform_storage_service import (
    compute_hourly_windows,
    load_cached_window,
)


NETWORK = "IA"
STATION = "AAFM"
LOCATION = "*"
CHANNEL = "SH*"

START = "2026-09-03T00:00:00"
END = "2026-09-03T04:00:00"


def describe_stream(label, stream):
    print(f"\n===== {label} =====")
    print(f"Trace count: {len(stream)}")

    if not stream:
        print("EMPTY")
        return

    for i, trace in enumerate(stream):
        data = trace.data

        print(f"\n--- Trace {i} ---")
        print(f"id           : {trace.id}")
        print(f"start        : {trace.stats.starttime}")
        print(f"end          : {trace.stats.endtime}")
        print(f"sampling_rate: {trace.stats.sampling_rate}")
        print(f"delta        : {trace.stats.delta}")
        print(f"npts         : {trace.stats.npts}")
        print(f"data type    : {type(data)}")
        print(f"is masked    : {np.ma.isMaskedArray(data)}")

        if np.ma.isMaskedArray(data):
            mask_count = int(np.ma.count_masked(data))
            print(f"masked count : {mask_count}")

        try:
            finite = np.isfinite(np.asarray(data, dtype=float))
            print(f"finite       : {bool(finite.all())}")
            print(f"non-finite   : {int((~finite).sum())}")
        except Exception as exc:
            print(f"finite check : ERROR: {exc}")


def main():
    db = SessionLocal()

    try:
        request_start = datetime.fromisoformat(START)
        request_end = datetime.fromisoformat(END)

        windows = compute_hourly_windows(
            request_start,
            request_end,
        )

        print("================================================")
        print(f"Station : {NETWORK}.{STATION}")
        print(f"Channel : {CHANNEL}")
        print(f"Request : {START} -> {END}")
        print("================================================")

        combined = Stream()

        for window_start, window_end in windows:
            print("\n")
            print("=" * 60)
            print(
                f"WINDOW: {window_start.isoformat()} "
                f"-> {window_end.isoformat()}"
            )
            print("=" * 60)

            stream = load_cached_window(
                db=db,
                network=NETWORK,
                station=STATION,
                location=LOCATION,
                channel=CHANNEL,
                window_start=window_start,
                window_end=window_end,
            )

            describe_stream("CACHE WINDOW", stream)

            if len(stream) == 0:
                print(">>> WINDOW KOSONG / TIDAK ADA CACHE")
            else:
                combined += stream

        print("\n\n")
        describe_stream("COMBINED BEFORE MERGE", combined)

        print("\n\n===== GAPS BEFORE MERGE =====")
        gaps = combined.get_gaps()

        if not gaps:
            print("Tidak ada gap yang terdeteksi.")
        else:
            for gap in gaps:
                print(gap)

        merged = combined.copy()

        print("\n\n===== MERGE =====")
        merged.merge(method=1)

        describe_stream("AFTER MERGE", merged)

        print("\n\n===== GAPS AFTER MERGE =====")
        gaps_after = merged.get_gaps()

        if not gaps_after:
            print("Tidak ada gap setelah merge.")
        else:
            for gap in gaps_after:
                print(gap)

    finally:
        db.close()


if __name__ == "__main__":
    main()