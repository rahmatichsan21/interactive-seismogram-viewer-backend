import base64
import io
import logging

import numpy as np
from scipy.signal import detrend

from obspy.signal.konnoohmachismoothing import (
    konno_ohmachi_smoothing,
)

from app.core.config import (
    HVSR_WINDOW_SECONDS,
    HVSR_OVERLAP,
    HVSR_KO_BANDWIDTH,
    HVSR_FMIN,
    HVSR_FMAX,
)
from app.services.psd_service import _PLOT_LOCK

logger = logging.getLogger(__name__)


def _validate_traces(n_trace, e_trace, z_trace):
    """
    Validasi wajib untuk HVSR:
    - Ketiga trace ada, tidak kosong, tidak NaN/Inf.
    - Tidak flat/konstan (SHE flat contoh: ditolak, bukan grafik palsu).
    - sampling_rate sama, starttime selaras, durasi sama.
    - Durasi cukup untuk minimal 1 window.
    Semua kegagalan -> ValueError dengan pesan Indonesia yang jelas.
    """
    if n_trace is None or e_trace is None or z_trace is None:
        raise ValueError("HVSR membutuhkan komponen N, E, dan Z.")

    names = {"N": n_trace, "E": e_trace, "Z": z_trace}
    for name, tr in names.items():
        if len(tr.data) == 0:
            raise ValueError(
                f"Komponen {name} kosong — HVSR tidak dapat dihitung."
            )
        if not np.isfinite(tr.data).all():
            raise ValueError(
                f"Komponen {name} mengandung NaN/Inf — "
                "HVSR tidak dapat dihitung."
            )
        mean_abs = abs(float(np.mean(tr.data)))
        std = float(np.std(tr.data))
        if std <= 1e-12 * (mean_abs + 1e-12):
            raise ValueError(
                f"Komponen {name} datanya konstan/flat — "
                "HVSR tidak dapat dihitung."
            )

    rates = {
        name: tr.stats.sampling_rate
        for name, tr in names.items()
    }
    base_rate = rates["N"]
    for name, rate in rates.items():
        if abs(rate - base_rate) > 1e-6:
            raise ValueError(
                f"Sampling rate komponen tidak cocok "
                f"(N={rates['N']}, {name}={rate}) — HVSR tidak "
                "dapat dihitung."
            )

    starts = {
        name: tr.stats.starttime
        for name, tr in names.items()
    }
    sample_interval = 1.0 / base_rate
    base_start = starts["N"]
    for name, start in starts.items():
        if abs((start - base_start)) > 0.5 * sample_interval:
            raise ValueError(
                f"Timestamp komponen {name} tidak selaras dengan "
                "komponen lain — HVSR tidak dapat dihitung."
            )

    durations = {
        name: len(tr.data) / tr.stats.sampling_rate
        for name, tr in names.items()
    }
    base_duration = durations["N"]
    for name, duration in durations.items():
        if abs(duration - base_duration) > 0.5 * sample_interval:
            raise ValueError(
                f"Durasi komponen {name} tidak cocok dengan "
                "komponen lain — HVSR tidak dapat dihitung."
            )

    if base_duration < HVSR_WINDOW_SECONDS:
        raise ValueError(
            f"Waveform terlalu pendek untuk HVSR "
            f"(durasi {base_duration:.1f}s < window "
            f"{HVSR_WINDOW_SECONDS:.0f}s)."
        )


def _window_spectrum(trace, window_npts, step_npts, fmin, fmax, ko_b):
    """FFT amplitudo per window, di-restrict [fmin,fmax], di-smooth
    Konno-Ohmachi. Return (freqs, spectra) di mana spectra shape
    (n_windows, n_freq)."""
    data = trace.data
    npts = len(data)
    n_windows = 1 + (npts - window_npts) // step_npts

    taper = np.hanning(window_npts)
    freqs_full = np.fft.rfftfreq(window_npts, 1.0 / trace.stats.sampling_rate)
    mask = (freqs_full >= fmin) & (freqs_full <= fmax)

    if not mask.any():
        raise ValueError(
            "Rentang frekuensi HVSR kosong pada sampling rate ini."
        )

    freqs = freqs_full[mask]
    spectra = np.empty((n_windows, freqs.shape[0]))

    for i in range(n_windows):
        segment = data[i * step_npts:i * step_npts + window_npts]
        segment = detrend(segment, type="linear")
        segment = segment * taper
        fft = np.fft.rfft(segment)
        amp = np.abs(fft)[mask]
        spectra[i] = konno_ohmachi_smoothing(
            amp, freqs, bandwidth=ko_b, normalize=False
        )

    return freqs, spectra


def compute_hvsr_image(
    n_trace,
    e_trace,
    z_trace,
    window_seconds=None,
    overlap=None,
    ko_bandwidth=None,
    fmin=None,
    fmax=None,
):
    """
    Hitung kurva HVSR (Nakamura H/V):
      H(f) = sqrt((N(f)^2 + E(f)^2) / 2)
      HVSR(f) = H(f) / Z(f)
    - Windowing, detrend, taper, FFT, Konno-Ohmachi smoothing.
    - Hasil akhir mean HVSR + variasi antar-window (band std).
    - Output: PNG base64 (mekanisme sama dengan PSD).
    """
    if window_seconds is None:
        window_seconds = HVSR_WINDOW_SECONDS
    if overlap is None:
        overlap = HVSR_OVERLAP
    if ko_bandwidth is None:
        ko_bandwidth = HVSR_KO_BANDWIDTH
    if fmin is None:
        fmin = HVSR_FMIN
    if fmax is None:
        fmax = HVSR_FMAX

    _validate_traces(n_trace, e_trace, z_trace)

    sampling_rate = n_trace.stats.sampling_rate
    nyquist = sampling_rate / 2.0
    fmin = float(max(fmin, 1e-6))
    fmax = float(min(fmax, nyquist * 0.95))

    if fmin >= fmax:
        raise ValueError(
            "Rentang frekuensi HVSR tidak valid (fmin >= fmax)."
        )

    window_npts = int(round(window_seconds * sampling_rate))
    step_npts = max(1, int(round(window_npts * (1.0 - overlap))))

    freqs, spec_n = _window_spectrum(
        n_trace, window_npts, step_npts, fmin, fmax, ko_bandwidth
    )
    _, spec_e = _window_spectrum(
        e_trace, window_npts, step_npts, fmin, fmax, ko_bandwidth
    )
    _, spec_z = _window_spectrum(
        z_trace, window_npts, step_npts, fmin, fmax, ko_bandwidth
    )

    horiz = np.sqrt((spec_n ** 2 + spec_e ** 2) / 2.0)

    z_min = 1e-12
    ratios = np.divide(
        horiz,
        spec_z,
        out=np.full_like(horiz, np.nan),
        where=spec_z > z_min,
    )

    valid_windows = np.isfinite(ratios).all(axis=1)
    ratios = ratios[valid_windows]

    if ratios.shape[0] == 0:
        raise ValueError(
            "Tidak ada window HVSR yang valid — "
            "HVSR tidak dapat dihitung."
        )

    mean_ratio = np.clip(np.mean(ratios, axis=0), 1e-3, None)
    std_ratio = np.std(ratios, axis=0)

    return _render_png(
        freqs,
        mean_ratio,
        std_ratio,
        n_trace,
        e_trace,
        z_trace,
    )


def _render_png(freqs, mean_ratio, std_ratio, n_trace, e_trace, z_trace):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base = n_trace.stats.channel[:-1]
    net = n_trace.stats.network or ""
    sta = n_trace.stats.station or ""
    loc = n_trace.stats.location or "--"
    title = (
        f"{net}.{sta}.{loc} [{base}N + {base}E + {base}Z] H/V"
    )

    # matplotlib.pyplot global tidak thread-safe — serialkan dengan
    # lock yang sama dengan PSD.
    with _PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.loglog(freqs, mean_ratio, color="#1f77b4", linewidth=2)
        ax.fill_between(
            freqs,
            mean_ratio - std_ratio,
            mean_ratio + std_ratio,
            color="#1f77b4",
            alpha=0.2,
            label="± 1 std (antar-window)",
        )
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("H/V")
        ax.set_title(title)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="upper right")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)

    buf.seek(0)
    return base64.b64encode(buf.read()).decode()