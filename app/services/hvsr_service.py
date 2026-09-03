import base64
import io
import logging

import numpy as np

import hvsrpy
from hvsrpy import (
    TimeSeries,
    SeismicRecording3C,
    preprocess,
    process,
    frequency_domain_window_rejection,
)
from hvsrpy.settings import (
    HvsrPreProcessingSettings,
    HvsrTraditionalProcessingSettings,
)

from app.core.config import (
    HVSR_WINDOW_SECONDS,
    HVSR_FMIN,
    HVSR_FMAX,
)
from app.services.psd_service import _PLOT_LOCK

logger = logging.getLogger(__name__)

# Detail metodologi internal (default reasonable hvsrpy, TIDAK di .env).
_HVSR_DETREND = "linear"
_HVSR_TAPER = ["tukey", 0.1]
_HVSR_KO_BANDWIDTH = 40
_HVSR_N_FREQ = 200
# Kombinasi horizontal: default hvsrpy (geometric_mean).
_HVSR_COMBINE_METHOD = "geometric_mean"
# Parameter internal rejection (Cox et al. 2020).
_HVSR_REJECTION_N = 2
# Fraksi Nyquist yang dipakai membatasi FMAX.
_NYQUIST_FRACTION = 0.95


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


def _build_processing_settings(window_seconds, fmin, fmax, nyquist):
    """Susun HvsrTraditionalProcessingSettings dengan grid frekuensi
    yang dibatasi Nyquist (hvsrpy menolak frekuensi > Nyquist)."""
    grid_max = min(fmax, nyquist * _NYQUIST_FRACTION)
    if fmin >= grid_max:
        raise ValueError(
            "Rentang frekuensi HVSR tidak valid "
            f"(fmin={fmin} Hz >= batas {grid_max:.2f} Hz)."
        )

    grid = np.geomspace(fmin, grid_max, _HVSR_N_FREQ)

    return HvsrTraditionalProcessingSettings(
        hvsrpy_version=hvsrpy.__version__,
        window_type_and_width=_HVSR_TAPER,
        smoothing=dict(
            operator="konno_and_ohmachi",
            bandwidth=_HVSR_KO_BANDWIDTH,
            center_frequencies_in_hz=grid,
        ),
        method_to_combine_horizontals=_HVSR_COMBINE_METHOD,
    )


def compute_hvsr_result(
    n_trace,
    e_trace,
    z_trace,
    window_seconds=None,
    fmin=None,
    fmax=None,
    rejection_enabled=False,
):
    """
    Hitung HVSR (Nakamura H/V) menggunakan hvsrpy sebagai engine utama.

    - Validasi trace tetap di project (_validate_traces).
    - preprocess/process/windowing/spectral/smoothing/combine/HV,
      kurva individual, mean & statistik, first peak, dan rejection
      (Cox et al. 2020, opsional) ditangani hvsrpy.
    - Output: dict {"image": PNG base64, "meta": {...}}.
    """
    if window_seconds is None:
        window_seconds = HVSR_WINDOW_SECONDS
    if fmin is None:
        fmin = HVSR_FMIN
    if fmax is None:
        fmax = HVSR_FMAX

    _validate_traces(n_trace, e_trace, z_trace)

    sampling_rate = n_trace.stats.sampling_rate
    nyquist = sampling_rate / 2.0

    prep_settings = HvsrPreProcessingSettings(
        hvsrpy_version=hvsrpy.__version__,
        window_length_in_seconds=float(window_seconds),
        detrend=_HVSR_DETREND,
    )

    record = SeismicRecording3C(
        ns=TimeSeries.from_trace(n_trace),
        ew=TimeSeries.from_trace(e_trace),
        vt=TimeSeries.from_trace(z_trace),
    )

    records = preprocess([record], prep_settings)

    proc_settings = _build_processing_settings(
        window_seconds, float(fmin), float(fmax), nyquist
    )

    hvsr = process(records, proc_settings)

    n_windows_total = int(hvsr.n_curves)

    if rejection_enabled:
        frequency_domain_window_rejection(hvsr, n=_HVSR_REJECTION_N)

    accepted_mask = np.asarray(hvsr.valid_window_boolean_mask, dtype=bool)
    n_accepted = int(accepted_mask.sum())

    if n_accepted == 0:
        raise ValueError(
            "Tidak ada window HVSR yang valid — "
            "HVSR tidak dapat dihitung."
        )

    frequency = np.asarray(hvsr.frequency)
    accepted_curves = np.asarray(hvsr.amplitude)[accepted_mask]

    mean_curve = np.asarray(hvsr.mean_curve())

    # ==========================================================
    # EKSPERIMEN BOUNDED PEAK SEARCH — OPSI D (fp/2 – 2*fp)
    # ==========================================================
    # Tujuan: menguji efek visual/metodologis membatasi pencarian
    # peak per-window (dan mean-curve peak) ke rentang di sekitar
    # fp, alih-alih unbounded/full-spectrum (baseline/opsi A).
    #
    # Urutan WAJIB:
    #   1) Hitung fp dulu dari mean curve TANPA bound (full range),
    #      supaya rentang eksperimen (fp/2, fp*2) punya basis fp
    #      yang belum bias oleh bound itu sendiri.
    #   2) Panggil hvsr.update_peaks_bounded(search_range_in_hz=...)
    #      — ini akan mem-bound baik peak per-window
    #      (peak_frequencies -> dipakai mean_fn/std_fn/nth_std_fn)
    #      MAUPUN mean_curve_peak() berikutnya (keduanya memakai
    #      hvsr._search_range_in_hz yang sama di hvsrpy 2.0.0).
    #   3) Hitung ulang fp via mean_curve_peak() (bounded) — nilainya
    #      seharusnya identik dengan langkah (1) karena fp pasti
    #      berada di dalam (fp/2, fp*2) secara konstruksi, tapi
    #      dihitung ulang agar konsisten dengan pipeline eksperimen.
    #
    # CATATAN (wajib dibaca sebelum membandingkan hasil):
    # - Ini HANYA eksperimen OPSI D (sedang dipertahankan sebagai
    #   konfigurasi sementara). Opsi B (fp/4-4fp), C (fp/3-3fp),
    #   E (fp/1.5-1.5fp) TIDAK aktif — ganti nilai
    #   `_EXPERIMENT_LOW_DIVISOR`/`_EXPERIMENT_HIGH_MULTIPLIER` di
    #   bawah untuk menguji opsi lain satu per satu, JANGAN
    #   aktifkan beberapa sekaligus.
    # - Rentang fp/2–2fp TIDAK diklaim sebagai "admissible range"
    #   resmi Geopsy — Geopsy tidak mempublikasikan formula/angka
    #   tersebut (lihat hasil audit sebelumnya). Ini murni heuristic
    #   internal aplikasi, tanpa dasar dokumentasi Geopsy/SESAME.
    _EXPERIMENT_LOW_DIVISOR = 2.0   # opsi D: fp / 2
    _EXPERIMENT_HIGH_MULTIPLIER = 2.0  # opsi D: fp * 2

    try:
        fp_unbounded, _ = hvsr.mean_curve_peak()
    except ValueError:
        fp_unbounded = None

    if fp_unbounded is not None:
        experiment_search_range = (
            fp_unbounded / _EXPERIMENT_LOW_DIVISOR,
            fp_unbounded * _EXPERIMENT_HIGH_MULTIPLIER,
        )
        hvsr.update_peaks_bounded(
            search_range_in_hz=experiment_search_range
        )
    # ==========================================================
    # END EKSPERIMEN OPSI D
    # ==========================================================

    # Statistik SD hanya terdefinisi bila ada >1 window valid. Dengan
    # satu window, hvsrpy melempar ValueError (mis. nth_std_curve).
    has_sd = n_accepted > 1
    if has_sd:
        lower_sd = np.asarray(hvsr.nth_std_curve(-1))
        upper_sd = np.asarray(hvsr.nth_std_curve(+1))
        fn_low = float(hvsr.nth_std_fn_frequency(-1))
        fn_high = float(hvsr.nth_std_fn_frequency(+1))
        mean_fn = float(hvsr.mean_fn_frequency())
        std_fn = float(hvsr.std_fn_frequency())
    else:
        lower_sd = None
        upper_sd = None
        fn_low = None
        fn_high = None
        mean_fn = None
        std_fn = None

    try:
        first_peak = hvsr.mean_curve_peak()
        peak_frequency = float(first_peak[0])
        peak_amplitude = float(first_peak[1])
    except ValueError:
        peak_frequency = None
        peak_amplitude = None

    # LOG EKSPERIMEN — catat fp, mean_fn, std_fn, fn_low, fn_high,
    # dan jumlah accepted windows untuk perbandingan opsi A/B/C/D/E.
    logger.info(
        "HVSR EXPERIMENT D (fp/%.1f - fp*%.1f): "
        "fp=%s mean_fn=%s std_fn=%s fn_low=%s fn_high=%s "
        "n_accepted=%s",
        _EXPERIMENT_LOW_DIVISOR, _EXPERIMENT_HIGH_MULTIPLIER,
        peak_frequency, mean_fn, std_fn, fn_low, fn_high, n_accepted,
    )

    meta = {
        "n_windows": n_windows_total,
        "n_accepted": n_accepted,
        "peak_frequency": peak_frequency,
        "peak_amplitude": peak_amplitude,
        "mean_fn_frequency": mean_fn,
        "std_fn_frequency": std_fn,
        "fn_low": fn_low,
        "fn_high": fn_high,
    }


    image = _render_png(
        frequency,
        accepted_curves,
        mean_curve,
        lower_sd,
        upper_sd,
        fn_low,
        fn_high,
        peak_frequency,
        peak_amplitude,
        mean_fn,
        std_fn,
        n_trace,
        e_trace,
        z_trace,
    )

    return {"image": image, "meta": meta}


def _render_png(
    frequency,
    accepted_curves,
    mean_curve,
    lower_sd,
    upper_sd,
    fn_low,
    fn_high,
    peak_frequency,
    peak_amplitude,
    mean_fn,
    std_fn,
    n_trace,
    e_trace,
    z_trace,
):
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

    has_sd = lower_sd is not None and upper_sd is not None
    has_fn_band = has_sd and fn_low is not None and fn_high is not None
    has_peak = peak_frequency is not None and peak_amplitude is not None

    with _PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(11, 5))

        # Band vertikal mean frequency ± 1 SD (lognormal hvsrpy):
        # [nth_std_fn_frequency(-1), nth_std_fn_frequency(+1)].
        if has_fn_band:
            ax.axvspan(
                fn_low,
                fn_high,
                color="#e91e63",
                alpha=0.22,
                zorder=0,
                label="Mean Frequency \u00b1 1 Standard Deviation",
            )

        for curve in accepted_curves:
            ax.loglog(
                frequency,
                curve,
                color="#94a3b8",
                linewidth=0.5,
                alpha=0.35,
                zorder=1,
            )

        # ±1 SD shaded area antara kurva lognormal nth_std_curve(±1).
        if has_sd:
            ax.fill_between(
                frequency,
                lower_sd,
                upper_sd,
                color="#1f77b4",
                alpha=0.2,
                zorder=2,
                label="\u00b1 1 SD",
            )

        ax.loglog(
            frequency,
            mean_curve,
            color="#1f77b4",
            linewidth=2,
            zorder=3,
            label="Mean",
        )

        # Kurva mean ± 1 SD (dashed) — statistik lognormal hvsrpy
        # (nth_std_curve), selalu positif, tidak perlu clipping.
        if has_sd:
            ax.loglog(
                frequency,
                upper_sd,
                color="#475569",
                linestyle="--",
                linewidth=1,
                alpha=0.9,
                zorder=3,
                label="Mean +1 SD",
            )
            ax.loglog(
                frequency,
                lower_sd,
                color="#475569",
                linestyle="--",
                linewidth=1,
                alpha=0.9,
                zorder=3,
                label="Mean -1 SD",
            )

        if has_peak:
            ax.plot(
                [peak_frequency],
                [peak_amplitude],
                "o",
                color="#d62728",
                markersize=7,
                zorder=4,
                label="First peak",
            )

        annotation = ""
        if has_peak:
            annotation += f"fp = {peak_frequency:.2f} Hz"
        if has_sd and mean_fn is not None and std_fn is not None:
            if annotation:
                annotation += "\n"
            annotation += (
                f"fn = {mean_fn:.2f} \u00b1 {std_fn:.2f} Hz"
            )

        if annotation:
            ax.text(
                0.02,
                0.97,
                annotation,
                transform=ax.transAxes,
                verticalalignment="top",
                fontsize=10,
                bbox=dict(
                    boxstyle="round,pad=0.35",
                    facecolor="white",
                    edgecolor="#cbd5e1",
                    alpha=0.9,
                ),
            )

        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("H/V")
        ax.set_title(title)
        ax.grid(True, which="both", alpha=0.3)
        # Legend dipindah ke LUAR area plot (kanan grafik) supaya
        # tidak menutupi kurva. `bbox_inches="tight"` di fig.savefig
        # di bawah akan otomatis memperluas canvas PNG agar legend
        # ini tidak terpotong. Semua 6 item legend yang sudah ada
        # (Mean Frequency ± 1 SD band, ± 1 SD, Mean, Mean +1 SD,
        # Mean -1 SD, First peak) dipertahankan apa adanya — hanya
        # posisi legend yang berubah, bukan isinya.
        ax.legend(
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            borderaxespad=0,
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)

    buf.seek(0)
    return base64.b64encode(buf.read()).decode()