import math

import matplotlib.pyplot as plt
import numpy as np

from app.services.waveform_service import download_waveform

# === Configuration ===
DECIMATION_DURATION_SECONDS = 6000
MAX_POINTS = 2000

NETWORK = "IA"
STATION = "AAFM"
LOCATION = "*"
CHANNEL = "SHZ"
START_TIME = "2025-07-01T00:00:00"
END_TIME = "2025-07-01T01:41:00"
# 101 menit, bukan tepat 100.
# SHZ @ 50 Hz, 6000 detik → threshold = 300000 sampel.
# Tepat 100 menit = 300000 sampel, tidak memicu decimate
# (300000 > 300000 = False). Tambah 1 menit supaya
# decimation_factor & num_buckets terhitung dan output benar-
# benar berubah vs raw.

# === Data ===
print(f"Mengunduh waveform...")
stream = download_waveform(
    network=NETWORK,
    station=STATION,
    location=LOCATION,
    channel=CHANNEL,
    start_time=START_TIME,
    end_time=END_TIME,
)
trace = stream[0]
data = trace.data
times = trace.times()  # detik relatif dari starttime

sampling_rate = trace.stats.sampling_rate
raw_point_count = len(data)
effective_threshold = DECIMATION_DURATION_SECONDS * sampling_rate

print(f"Channel            : {trace.stats.channel}")
print(f"Sampling rate      : {sampling_rate} Hz")
print(f"Raw point count    : {raw_point_count}")
print(f"Threshold          : {effective_threshold} "
      f"({DECIMATION_DURATION_SECONDS}s × {sampling_rate} Hz)")
print(f"Should decimate    : {raw_point_count > effective_threshold}")

if raw_point_count <= effective_threshold:
    print()
    print("ERROR: Decimation tidak terpicu.")
    print("Perpanjang END_TIME atau pilih channel dengan "
          "sampling_rate lebih tinggi.")
    exit(1)

decimation_factor = math.ceil(raw_point_count / MAX_POINTS)
num_buckets = math.ceil(raw_point_count / decimation_factor)

print(f"Decimation factor  : {decimation_factor}")
print(f"Bucket count       : {num_buckets}")

# === Algorithm Functions ===

def _pad_and_bucket(arr, df, nb):
    """Pad lalu reshape menjadi (nb, df). Replika _decimate_min_max()."""
    pad_len = nb * df - len(arr)
    padded = (
        np.pad(arr, (0, pad_len), mode="edge")
        if pad_len > 0
        else arr
    )
    return padded.reshape(nb, df)


def algo_raw(arr, t, df, nb):
    return t, arr


def algo_envelope(arr, t, df, nb):
    """Replika persis _decimate_min_max()."""
    buckets = _pad_and_bucket(arr, df, nb)
    amp_min = buckets.min(axis=1)
    amp_max = buckets.max(axis=1)
    t_bucket = t[::df][:nb]
    return t_bucket, amp_min, amp_max


def algo_temporal(arr, t, df, nb):
    """Temporal-order extrema — argmin & argmax per bucket,
    merge-sort by original sample position, no duplicate."""
    buckets = _pad_and_bucket(arr, df, nb)

    idx_min = buckets.argmin(axis=1)
    idx_max = buckets.argmax(axis=1)

    offset = np.arange(nb) * df
    global_indices = np.unique(
        np.sort(np.concatenate([offset + idx_min, offset + idx_max]))
    )

    return t[global_indices], arr[global_indices]


def algo_mean(arr, t, df, nb):
    """Bucket mean dengan timestamps titik-tengah bucket."""
    buckets = _pad_and_bucket(arr, df, nb)
    amp_mean = buckets.mean(axis=1)
    t_bucket_start = t[::df][:nb]
    t_mid = t_bucket_start + df / sampling_rate / 2
    return t_mid, amp_mean


# === Jalankan semua algoritma ===
t_raw, amp_raw = algo_raw(data, times, decimation_factor, num_buckets)
t_env, env_min, env_max = algo_envelope(data, times, decimation_factor, num_buckets)
t_tmp, amp_tmp = algo_temporal(data, times, decimation_factor, num_buckets)
t_avg, amp_avg = algo_mean(data, times, decimation_factor, num_buckets)

print()
print(f"Raw points         : {len(amp_raw)}")
print(f"Envelope buckets   : {len(env_min)}")
print(f"Temporal points    : {len(amp_tmp)}")
print(f"Mean buckets       : {len(amp_avg)}")

# === Plot ===
fig, axes = plt.subplots(3, 1, figsize=(22, 12), sharex=True, sharey=True)

COLOR_RAW = "lightgray"
COLOR_ENV = "#1f77b4"
COLOR_TMP = "#2ca02c"
COLOR_AVG = "#ff7f0e"

y_min, y_max = float(amp_raw.min()), float(amp_raw.max())
y_pad = max(1.0, (y_max - y_min) * 0.08)
y_lim = (y_min - y_pad, y_max + y_pad)
x_lim = (times[0], times[-1])

# --- Subplot 1: Envelope vs Raw ---
ax = axes[0]
ax.plot(t_raw, amp_raw, color=COLOR_RAW, linewidth=0.5, zorder=1)
ax.fill_between(t_env, env_min, env_max, alpha=0.15, color=COLOR_ENV, zorder=2)
ax.plot(t_env, env_min, color=COLOR_ENV, linewidth=0.5, zorder=3)
ax.plot(t_env, env_max, color=COLOR_ENV, linewidth=0.5, zorder=3)
ax.set_title(
    f"Envelope (current implementation) vs Raw  —  "
    f"{len(amp_raw):,} → {len(env_min):,} buckets",
    fontsize=13,
)

# --- Subplot 2: Temporal-order vs Raw ---
ax = axes[1]
ax.plot(t_raw, amp_raw, color=COLOR_RAW, linewidth=0.5, zorder=1)
ax.plot(t_tmp, amp_tmp, color=COLOR_TMP, linewidth=0.8, zorder=2)
ax.set_title(
    f"Temporal-order Min/Max vs Raw  —  "
    f"{len(amp_raw):,} → {len(amp_tmp):,} points",
    fontsize=13,
)

# --- Subplot 3: Bucket Mean vs Raw ---
ax = axes[2]
ax.plot(t_raw, amp_raw, color=COLOR_RAW, linewidth=0.5, zorder=1)
ax.plot(t_avg, amp_avg, color=COLOR_AVG, linewidth=0.8, zorder=2)
ax.set_title(
    f"Bucket Mean vs Raw  —  "
    f"{len(amp_raw):,} → {len(amp_avg):,} points",
    fontsize=13,
)

for ax in axes:
    ax.set_xlim(x_lim)
    ax.set_ylim(y_lim)
    ax.set_ylabel("Amplitude", fontsize=11)

axes[-1].set_xlabel(
    f"Seconds since {START_TIME} (UTC)"
)
axes[-1].legend(
    ["Raw waveform", "Candidate"],
    loc="upper right",
    fontsize=10,
)
axes[0].legend(
    ["Raw waveform", "Envelope (min/max)"],
    loc="upper right",
    fontsize=10,
)
axes[1].legend(
    ["Raw waveform", "Temporal-order"],
    loc="upper right",
    fontsize=10,
)

plt.tight_layout()
output_path = "visual_compare.png"
plt.savefig(output_path, dpi=150)
plt.close()

print()
print(f"Saved: {output_path}")
