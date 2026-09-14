from __future__ import annotations

import os

import numpy as np
from dotenv import load_dotenv
from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BMKG_URL = os.getenv("BMKG_URL")
BMKG_USERNAME = os.getenv("BMKG_USERNAME")
BMKG_PASSWORD = os.getenv("BMKG_PASSWORD")

if not BMKG_URL:
    raise RuntimeError("BMKG_URL tidak ditemukan di .env")

if not BMKG_USERNAME or not BMKG_PASSWORD:
    raise RuntimeError(
        "BMKG_USERNAME / BMKG_PASSWORD tidak ditemukan di .env"
    )


NETWORK = "IA"
STATION = "AAFM"
LOCATION = "*"
CHANNEL = "SH*"

START = UTCDateTime("2026-09-03T00:00:00")
END = UTCDateTime("2026-09-03T04:00:00")

GAP_THRESHOLD_PERCENT = 30.0


# ============================================================
# HELPERS
# ============================================================

def describe(label: str, stream: Stream) -> None:
    print(f"\n=== {label} ===")
    print(f"trace_count = {len(stream)}")

    for i, trace in enumerate(stream):
        data = trace.data

        masked_count = (
            np.ma.count_masked(data)
            if np.ma.isMaskedArray(data)
            else 0
        )

        print(
            f"[{i}] {trace.id} | "
            f"{trace.stats.starttime} -> "
            f"{trace.stats.endtime} | "
            f"npts={trace.stats.npts} | "
            f"masked={masked_count}"
        )


def download_waveform(client: Client) -> Stream:
    stream = Stream()

    current = START

    while current < END:
        next_time = min(
            current + 3600,
            END,
        )

        print(
            f"Request: "
            f"{current} -> {next_time}"
        )

        try:
            hourly = client.get_waveforms(
                network=NETWORK,
                station=STATION,
                location=LOCATION,
                channel=CHANNEL,
                starttime=current,
                endtime=next_time,
                attach_response=False,
            )

            print(
                f"  received {len(hourly)} trace(s)"
            )

            stream += hourly

        except Exception as exc:
            print(
                f"  request gagal: "
                f"{type(exc).__name__}: {exc}"
            )

        current = next_time

    return stream


def merge_preserve_gap(stream: Stream) -> Stream:
    merged = stream.copy()

    merged.merge(
        method=1,
        fill_value=None,
    )

    return merged


def calculate_gap_percent(trace) -> None:
    gaps = Stream([trace]).get_gaps()

    if not gaps:
        print(
            f"{trace.id}: tidak ada gap."
        )
        return

    total_duration = (
        trace.stats.endtime - trace.stats.starttime
    )

    print(f"\nGap analysis: {trace.id}")
    print(
        f"total duration = "
        f"{total_duration:.3f} s"
    )

    for gap in gaps:
        gap_start = gap[4]
        gap_end = gap[5]
        gap_duration = gap[6]

        percent = (
            gap_duration /
            total_duration *
            100
        )

        print(
            f"gap = {gap_start} -> {gap_end}"
        )
        print(
            f"gap duration = "
            f"{gap_duration:.3f} s"
        )
        print(
            f"gap percentage = "
            f"{percent:.2f}%"
        )

        if percent > GAP_THRESHOLD_PERCENT:
            print(
                f"DECISION: SPLIT "
                f"(>{GAP_THRESHOLD_PERCENT:.0f}%)"
            )
        else:
            print(
                f"DECISION: tidak melewati threshold "
                f"({GAP_THRESHOLD_PERCENT:.0f}%)"
            )


def split_and_process_filter(trace):
    print(
        f"\n--- FILTER: {trace.id} ---"
    )

    segments = Stream([trace]).split()

    print(
        f"segment count = {len(segments)}"
    )

    processed = Stream()

    for index, segment in enumerate(segments):
        print(
            f"segment {index}: "
            f"{segment.stats.starttime} -> "
            f"{segment.stats.endtime} | "
            f"npts={segment.stats.npts}"
        )

        candidate = segment.copy()

        candidate.filter(
            "bandpass",
            freqmin=0.1,
            freqmax=10.0,
            corners=4,
            zerophase=True,
        )

        candidate.stats.segment_index = index

        processed += candidate

    print(
        f"processed segment count = "
        f"{len(processed)}"
    )

    merged = processed.copy()

    merged.merge(
        method=1,
        fill_value=0,
    )

    print(
        f"after merge: "
        f"trace_count={len(merged)}"
    )

    for result in merged:
        data = np.asarray(
            result.data,
            dtype=float,
        )

        print(
            f"{result.id} | "
            f"npts={result.stats.npts} | "
            f"min={np.min(data):.6e} | "
            f"max={np.max(data):.6e}"
        )

        gaps = Stream([result]).get_gaps()

        print(
            f"remaining gaps = {len(gaps)}"
        )

        # Cari jumlah zero pada area gap setelah merge.
        # Karena data asli juga bisa secara kebetulan bernilai zero,
        # angka ini hanya statistik kasar.
        zero_count = np.count_nonzero(data == 0)

        print(
            f"zero samples = {zero_count}"
        )

    return merged


def split_and_process_response(
    client: Client,
    trace,
):
    print(
        f"\n--- INSTRUMENT CORRECTION: "
        f"{trace.id} ---"
    )

    inventory = client.get_stations(
        network=NETWORK,
        station=STATION,
        location=LOCATION,
        channel=CHANNEL,
        starttime=START,
        endtime=END,
        level="response",
    )

    segments = Stream([trace]).split()

    print(
        f"segment count = {len(segments)}"
    )

    processed = Stream()

    for index, segment in enumerate(segments):
        print(
            f"processing segment {index}: "
            f"{segment.stats.starttime} -> "
            f"{segment.stats.endtime}"
        )

        candidate = segment.copy()

        candidate.remove_response(
            inventory=inventory,
            output="VEL",
            water_level=60,
        )

        candidate.stats.segment_index = index

        processed += candidate

    merged = processed.copy()

    merged.merge(
        method=1,
        fill_value=0,
    )

    print(
        f"after merge: "
        f"trace_count={len(merged)}"
    )

    return merged


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("==============================================")
    print("ObsPy GAP → SPLIT → PROCESS → MERGE → ZERO")
    print("==============================================")

    print(
        f"Window: {START} -> {END}"
    )

    client = Client(
        BMKG_URL,
        user=BMKG_USERNAME,
        password=BMKG_PASSWORD,
    )

    # --------------------------------------------------------
    # 1. Download
    # --------------------------------------------------------

    raw = download_waveform(client)

    if len(raw) == 0:
        raise RuntimeError(
            "Tidak ada waveform dari FDSN."
        )

    describe(
        "RAW DATA",
        raw,
    )

    # --------------------------------------------------------
    # 2. Merge, tetapi gap tetap dipertahankan
    # --------------------------------------------------------

    merged = merge_preserve_gap(raw)

    describe(
        "MERGED - GAP PRESERVED",
        merged,
    )

    # --------------------------------------------------------
    # 3. Analisis gap
    # --------------------------------------------------------

    for trace in merged:
        calculate_gap_percent(trace)

    # --------------------------------------------------------
    # 4. Filter
    # --------------------------------------------------------

    print(
        "\n\n=============================================="
    )
    print("FILTER WORKFLOW")
    print(
        "=============================================="
    )

    for trace in merged:
        split_and_process_filter(trace)

    # --------------------------------------------------------
    # 5. Instrument correction
    # --------------------------------------------------------

    print(
        "\n\n=============================================="
    )
    print("INSTRUMENT CORRECTION WORKFLOW")
    print(
        "=============================================="
    )

    for trace in merged:
        try:
            split_and_process_response(
                client,
                trace,
            )
        except Exception as exc:
            print(
                f"[ERROR] {trace.id}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        "\n=============================================="
    )
    print("SELESAI")
    print(
        "=============================================="
    )


if __name__ == "__main__":
    main()