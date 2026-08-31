import base64
import logging
import os
import tempfile
import threading

from obspy.signal import PPSD

from app.core.config import (
    PPSD_LENGTH_SECONDS,
    PPSD_OVERLAP,
)

logger = logging.getLogger(__name__)

# matplotlib.pyplot global-state tidak thread-safe. Beberapa request
# PSD paralel (mis. SHE/SHN/SHZ) memanggil PPSD.plot() bersamaan →
# plt.figure()/plt.savefig()/plt.close() di thread berbeda bisa
# menghasilkan PNG blank/parsial. Lock ini menserialkan tahap plot.
_PLOT_LOCK = threading.Lock()


def compute_psd_image(
    trace,
    inventory,
    ppsd_length=None,
    overlap=None,
):
    """
    Hitung PSD menggunakan ObsPy PPSD dan render ke PNG (base64).

    - Menggunakan Inventory (StationXML) utk instrument response
      correction (PPSD mengoreksi response secara internal).
    - `ppsd_length` & `overlap` default dari config (PPSD_LENGTH_SECONDS,
      PPSD_OVERLAP) — keduanya memengaruhi hasil dan masuk cache key.
    - Waveform lebih pendek dari ppsd_length -> ValueError (error jelas),
      TIDAK ada fallback ke durasi yang lebih pendek.
    - Output: PNG base64 (konsisten dgn mekanisme image spectrogram).
    """
    if ppsd_length is None:
        ppsd_length = PPSD_LENGTH_SECONDS
    if overlap is None:
        overlap = PPSD_OVERLAP

    duration = trace.stats.endtime - trace.stats.starttime

    if duration < ppsd_length:
        raise ValueError(
            f"Waveform terlalu pendek untuk PSD "
            f"(durasi {duration:.1f}s < ppsd_length {ppsd_length}s)."
        )

    ppsd = PPSD(
        stats=trace.stats,
        metadata=inventory,
        ppsd_length=float(ppsd_length),
        overlap=overlap,
    )

    ppsd.add(trace)

    if not ppsd.times_processed:
        raise ValueError(
            f"Waveform terlalu pendek untuk PSD "
            f"(minimal {ppsd_length}s)."
        )

    ppsd.calculate_histogram()

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        with _PLOT_LOCK:
            ppsd.plot(
                filename=path,
                show=False,
                show_noise_models=True,
                show_percentiles=True,
                grid=True,
            )
        with open(path, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(path):
            os.remove(path)

    return base64.b64encode(data).decode()