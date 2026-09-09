"""
benchmark/fdsn_cache_benchmark.py — Retest KHUSUS 5 skenario FDSN
cached/uncached/mixed (yang sebelumnya gagal di run ram_cpu_benchmark.py).

Script TERPISAH dari benchmark/ram_cpu_benchmark.py:
  - ram_cpu_benchmark.py TIDAK diubah sama sekali.
  - Script ini TIDAK menjalankan/mengulang skenario lain (Local Upload,
    Processing/Trim/Filter/Instrument Correction, Spectrogram, PSD,
    HVSR) — HANYA 5 skenario FDSN di bawah ini.

5 skenario yang diuji (semua lewat GET /api/waveform &
GET /api/waveform/status, endpoint yang sudah ada — TIDAK mengubah
kode aplikasi apapun):
  1. fdsn_cached        - FDSN Cached        (SEMUA stasiun terpilih)
  2. fdsn_uncached       - FDSN Uncached       (SEMUA stasiun terpilih)
  3. fdsn_multi_cached   - FDSN Multi Cached   (SEMUA stasiun terpilih)
  4. fdsn_multi_uncached - FDSN Multi Uncached (SEMUA stasiun terpilih)
  5. fdsn_multi_mixed    - FDSN Mixed          (dibagi cached/uncached)

Aturan station (WAJIB persis mengikuti --stations, TIDAK ADA hardcode
"1 station"/"4 station"/"AAFM" di mana pun di script ini):
  --stations AAFM AAI            -> 2 station
  --stations AAFM AAI ABJI       -> 3 station
  --stations AAFM AAI ABJI ABSM  -> 4 station
  --stations AAFM AAI ABJI ABSM ACJM -> 5 station (maksimum)

Pembagian scenario Mixed (jumlah ganjil -> uncached mendominasi):
  2 station -> 1 cached + 1 uncached
  3 station -> 1 cached + 2 uncached
  4 station -> 2 cached + 2 uncached
  5 station -> 2 cached + 3 uncached

Logika cache (per station x channel x window 24 jam, live-check ke
GET /api/waveform/status, TIDAK PERNAH diasumsikan):
  - cached   = SEMUA channel di window itu sudah download_needed=False.
  - uncached = TIDAK SATU channel pun cached di window itu.
  - target awal = KEMARIN (tanggal lokal komputer yang menjalankan
    script ini, TIDAK PERNAH hari ini, TIDAK di-hardcode). Kalau
    ternyata (sebagian) sudah cached, mundur satu hari, dst
    (fdsn.max_lookback_days dari scenarios.json, default 30).
  - scenario cached: window di-PRIME dulu (untimed, idempotent) sampai
    fully cached, verifikasi, baru measured call (harus HIT).
  - scenario uncached: measured call TANPA priming (guaranteed MISS),
    lalu verifikasi pasca-request bahwa semua channel sudah menjadi
    cached. Kalau setelah request masih ada download_needed=True untuk
    channel manapun, scenario DIANGGAP GAGAL (bukan sukses diam-diam)
    — status FAILED mencantumkan persis station, channel, dan tanggal
    yang gagal.

Pengukuran RAM/CPU pakai metode SAMA PERSIS dengan
ram_cpu_benchmark.py (RSS + CPU% via psutil, baseline window sebelum
request, window measured selama request, window stabilisasi sesudah
request): RAM Before, RAM Peak, RAM Stable, Delta Stable, CPU
Average, CPU Peak, Duration, Status.

Output disimpan ke benchmark/results/:
  {run_id}_fdsn_cache_summary.csv
  {run_id}_fdsn_cache_raw_timeseries.json

Cara pakai:
  python benchmark/fdsn_cache_benchmark.py --attach-pid 10956 \
      --stations AAFM AAI

  python benchmark/fdsn_cache_benchmark.py \
      --spawn "uvicorn app.main:app --host 127.0.0.1 --port 8000" \
      --stations AAFM AAI ABJI --date 2026-09-05
"""

import argparse
import csv
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import psutil

BENCH_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = BENCH_DIR / "scenarios.json"
RESULTS_DIR = BENCH_DIR / "results"

SAMPLE_INTERVAL_SEC = 0.2
BASELINE_WINDOW_SEC = 1.5
STABLE_WAIT_SEC = 2.0
STABLE_WINDOW_SEC = 1.5

MIN_STATIONS = 1
MAX_STATIONS = 5


# --------------------------------------------------------------------------
# HTTP helpers (stdlib only — sengaja duplikat kecil dari
# ram_cpu_benchmark.py supaya script ini benar-benar berdiri sendiri
# dan TIDAK mengimpor/mengubah ram_cpu_benchmark.py sama sekali)
# --------------------------------------------------------------------------

def http_json(method, url, timeout=300):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            detail = json.loads(body)
        except Exception:
            detail = body.decode("utf-8", errors="replace")
        return exc.code, detail


def _qs(params):
    return "&".join(
        f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v is not None
    )


# --------------------------------------------------------------------------
# RAM/CPU sampler — identik metodenya dengan ram_cpu_benchmark.py
# (baseline window sebelum request, window measured selama request,
# window stabilisasi sesudah request; cache objek psutil.Process per
# PID supaya cpu_percent() akurat antar tick).
# --------------------------------------------------------------------------

class Sampler:
    def __init__(self, pid):
        self.proc = psutil.Process(pid)
        self._proc_cache = {pid: self.proc}
        self.proc.cpu_percent(interval=None)  # priming, hasil diabaikan

        self._stop = threading.Event()
        self._samples = []  # list of (timestamp, rss_mb, cpu_pct)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _all_procs(self):
        try:
            children = self.proc.children(recursive=True)
        except psutil.Error:
            children = []

        current_pids = {self.proc.pid}
        for child in children:
            current_pids.add(child.pid)
            if child.pid not in self._proc_cache:
                self._proc_cache[child.pid] = child
                try:
                    child.cpu_percent(interval=None)
                except psutil.Error:
                    pass

        for stale_pid in list(self._proc_cache.keys()):
            if stale_pid not in current_pids:
                del self._proc_cache[stale_pid]

        return list(self._proc_cache.values())

    def _sample_once(self):
        rss_total = 0
        cpu_total = 0.0
        for p in self._all_procs():
            try:
                rss_total += p.memory_info().rss
                cpu_total += p.cpu_percent(interval=None)
            except psutil.Error:
                continue
        return rss_total / (1024 * 1024), cpu_total

    def _run(self):
        while not self._stop.is_set():
            t = time.time()
            rss_mb, cpu_pct = self._sample_once()
            with self._lock:
                self._samples.append((t, rss_mb, cpu_pct))
            time.sleep(SAMPLE_INTERVAL_SEC)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def samples_between(self, t_start, t_end):
        with self._lock:
            snap = list(self._samples)
        return [s for s in snap if t_start <= s[0] <= t_end]

    def all_samples(self):
        with self._lock:
            return list(self._samples)


def mean(values):
    return sum(values) / len(values) if values else float("nan")


# --------------------------------------------------------------------------
# Server lifecycle — identik pola dengan ram_cpu_benchmark.py
# --------------------------------------------------------------------------

class ServerHandle:
    def __init__(self, spawn_cmd=None, attach_pid=None, cwd=None):
        self.spawn_cmd = spawn_cmd
        self.attach_pid = attach_pid
        self.cwd = cwd
        self._proc = None

    def start(self):
        if self.attach_pid:
            return self.attach_pid
        self._proc = subprocess.Popen(
            self.spawn_cmd,
            shell=True,
            cwd=self.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        return self._proc.pid

    def restart(self):
        if self.attach_pid:
            return self.attach_pid  # attach mode: reset dilakukan manual
        self.stop()
        return self.start()

    def stop(self):
        if self._proc is not None:
            try:
                parent = psutil.Process(self._proc.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
                parent.wait(timeout=10)
            except psutil.Error:
                pass
            self._proc = None

    def current_pid(self):
        return self.attach_pid or self._proc.pid


# --------------------------------------------------------------------------
# FDSN cache helpers — window 24 jam, target_date = kemarin (otomatis,
# lokal, tidak pernah hardcode), status cached/uncached live-check per
# station x channel lewat GET /api/waveform/status.
# --------------------------------------------------------------------------

def default_target_date():
    """Tanggal kalender KEMARIN menurut waktu lokal komputer yang
    menjalankan script ini — TIDAK PERNAH hari ini, TIDAK hardcode."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _day_range(date_str, window_hours=24):
    start = datetime.fromisoformat(date_str + "T00:00:00")
    end = start + timedelta(hours=window_hours)
    return start.isoformat(), end.isoformat()


def check_waveform_cached(base_url, fdsn_cfg, station, channel, start_time, end_time):
    """GET /api/waveform/status — read-only, TIDAK mengisi cache.
    True kalau (station, channel, start, end) SUDAH fully cached."""
    params = {
        "network": fdsn_cfg["network"],
        "station": station,
        "location": fdsn_cfg["location"],
        "channel": channel,
        "start_time": start_time,
        "end_time": end_time,
    }
    status, resp = http_json(
        "GET", f"{base_url}/api/waveform/status?{_qs(params)}"
    )
    if status != 200:
        raise RuntimeError(
            f"GET /api/waveform/status gagal untuk {station}.{channel}: "
            f"HTTP {status} {resp}"
        )
    return not resp["download_needed"]


def resolve_uncached_window(base_url, fdsn_cfg, station, channels, start_date):
    """Cari window 24-jam yang BENAR-BENAR uncached (download_needed=True
    di SEMUA channel) untuk `station`, mulai dari `start_date` mundur ke
    date-1, date-2, dst kalau tanggal itu ternyata (sebagian) sudah
    cached. Status selalu dicek LIVE, tidak pernah diasumsikan.

    Return dict: {"date", "start", "end", "reason", "cached_before"}
    """
    max_lookback = fdsn_cfg.get("max_lookback_days", 30)
    date = datetime.fromisoformat(start_date)
    reason = f"target date {start_date} belum ter-cache untuk semua channel"
    cached_before = False

    for _ in range(max_lookback):
        date_str = date.strftime("%Y-%m-%d")
        start, end = _day_range(date_str)
        status_map = {
            ch: check_waveform_cached(base_url, fdsn_cfg, station, ch, start, end)
            for ch in channels
        }
        if not any(status_map.values()):
            return {
                "date": date_str, "start": start, "end": end,
                "reason": reason, "cached_before": cached_before,
            }

        cached_before = True
        cached_chs = [ch for ch, is_cached in status_map.items() if is_cached]
        reason = (
            f"{date_str} sudah (sebagian) ter-cache untuk channel "
            f"{cached_chs} — mundur ke tanggal sebelumnya"
        )
        date -= timedelta(days=1)

    raise RuntimeError(
        f"Tidak menemukan window uncached untuk station={station} "
        f"channels={channels} dalam {max_lookback} hari mundur dari "
        f"{start_date}. Semua tanggal yang dicoba sudah (sebagian) "
        "ter-cache — perluas fdsn.max_lookback_days di scenarios.json "
        "kalau ini memang diharapkan."
    )


def _fdsn_call_all(base_url, fdsn_cfg, stations, start_time, end_time, channels):
    """GET /api/waveform untuk setiap (station, channel) di `stations`
    x `channels`. Channel SELALU konkret satu-satu, TIDAK PERNAH
    wildcard."""
    for station in stations:
        for channel in channels:
            params = {
                "network": fdsn_cfg["network"],
                "station": station,
                "location": fdsn_cfg["location"],
                "channel": channel,
                "start_time": start_time,
                "end_time": end_time,
            }
            if fdsn_cfg.get("max_points"):
                params["max_points"] = fdsn_cfg["max_points"]
            status, resp = http_json(
                "GET", f"{base_url}/api/waveform?{_qs(params)}"
            )
            if status != 200:
                raise RuntimeError(
                    f"FDSN load {station}.{channel} failed: HTTP {status} {resp}"
                )


def prime_window(base_url, fdsn_cfg, station, channels, start, end):
    """Panggilan untimed supaya window benar-benar fully cached.
    Idempotent — aman walau sebagian channel sudah cached."""
    _fdsn_call_all(base_url, fdsn_cfg, [station], start, end, channels)


def verify_fully_cached(base_url, fdsn_cfg, station, channels, start, end, context):
    """Assert semua channel benar-benar fully cached SETELAH sebuah
    request. Kalau ada channel yang MASIH download_needed=True, ini
    dianggap GAGAL (bukan sukses diam-diam) — pesan mencantumkan
    persis station, channel, dan tanggal (window) yang gagal."""
    status_map = {
        ch: check_waveform_cached(base_url, fdsn_cfg, station, ch, start, end)
        for ch in channels
    }
    not_cached = [ch for ch, ok in status_map.items() if not ok]
    if not_cached:
        raise RuntimeError(
            f"[{context}] Verifikasi pasca-request GAGAL: station={station} "
            f"channel={not_cached} window={start}->{end} MASIH "
            "download_needed=True (kemungkinan ada window/jam yang gagal "
            "di-download parsial)."
        )
    print(f"      [VERIFY] {context}: {station} @ {start}->{end} "
          "FULLY CACHED untuk semua channel.")


def split_mixed_stations(stations):
    """Bagi `stations` jadi (cached_stations, uncached_stations) untuk
    scenario Mixed. Jumlah ganjil -> uncached mendominasi:
      2 -> 1 cached + 1 uncached
      3 -> 1 cached + 2 uncached
      4 -> 2 cached + 2 uncached
      5 -> 2 cached + 3 uncached
    """
    half = len(stations) // 2
    cached_stations = stations[:half] or stations[:1]
    uncached_stations = stations[half:] if half else stations[1:]
    return cached_stations, uncached_stations


# --------------------------------------------------------------------------
# Scenario prepare functions — SEMUA memakai SELURUH `stations` yang
# diberikan lewat --stations (dinamis 1-5), TIDAK ADA hardcode
# "1 station"/"4 station"/"AAFM" di mana pun.
# --------------------------------------------------------------------------

def prepare_fdsn_cached(base_url, fdsn_cfg, stations, scn_id):
    """SEMUA stasiun terpilih — CACHED: resolve window uncached per
    stasiun (live-check, mundur tanggal kalau perlu), PRIME (untimed,
    idempotent), verifikasi FULLY CACHED, baru measured call (harus
    HIT semua)."""
    channels = fdsn_cfg["channels"]
    windows = {}
    for station in stations:
        res = resolve_uncached_window(
            base_url, fdsn_cfg, station, channels, fdsn_cfg["target_date"]
        )
        print(f"[INFO] {scn_id}: station={station} channels={channels} "
              f"date={res['date']} status=akan di-PRIME lalu diukur "
              f"sebagai CACHED"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        prime_window(base_url, fdsn_cfg, station, channels, res["start"], res["end"])
        verify_fully_cached(base_url, fdsn_cfg, station, channels, res["start"],
                             res["end"], f"{scn_id}/{station} (pre-measure)")
        windows[station] = res

    def measure():
        for station in stations:
            res = windows[station]
            _fdsn_call_all(base_url, fdsn_cfg, [station], res["start"], res["end"],
                            channels)

    return measure, (lambda: None)


def prepare_fdsn_uncached(base_url, fdsn_cfg, stations, scn_id):
    """SEMUA stasiun terpilih — UNCACHED: resolve window yang
    BENAR-BENAR belum cached per stasiun, measured call TANPA priming
    (guaranteed miss). Verifikasi semua jadi cached di cleanup_fn."""
    channels = fdsn_cfg["channels"]
    windows = {}
    for station in stations:
        res = resolve_uncached_window(
            base_url, fdsn_cfg, station, channels, fdsn_cfg["target_date"]
        )
        print(f"[INFO] {scn_id}: station={station} channels={channels} "
              f"date={res['date']} status=UNCACHED"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        windows[station] = res

    def measure():
        for station in stations:
            res = windows[station]
            _fdsn_call_all(base_url, fdsn_cfg, [station], res["start"], res["end"],
                            channels)

    def cleanup():
        for station in stations:
            res = windows[station]
            verify_fully_cached(base_url, fdsn_cfg, station, channels, res["start"],
                                 res["end"], f"{scn_id}/{station} (post-measure)")

    return measure, cleanup


def prepare_fdsn_mixed(base_url, fdsn_cfg, stations, scn_id):
    """Bagi `stations` jadi kelompok CACHED (resolve+prime+verify) dan
    UNCACHED (resolve saja) via split_mixed_stations(). SATU measured
    scenario memanggil KEDUA kelompok secara sequential."""
    if len(stations) < 2:
        raise RuntimeError(
            "fdsn_multi_mixed butuh minimal 2 stasiun (untuk kelompok "
            f"cached + uncached), tapi hanya {len(stations)} dipilih "
            f"({stations}). Jalankan dengan --stations lebih dari satu."
        )

    channels = fdsn_cfg["channels"]
    cached_stations, uncached_stations = split_mixed_stations(stations)
    print(f"[INFO] {scn_id}: pembagian = {len(cached_stations)} cached "
          f"{cached_stations} + {len(uncached_stations)} uncached "
          f"{uncached_stations}")

    windows = {}
    for station in cached_stations:
        res = resolve_uncached_window(
            base_url, fdsn_cfg, station, channels, fdsn_cfg["target_date"]
        )
        print(f"[INFO] {scn_id}: station={station} role=CACHED "
              f"channels={channels} date={res['date']}"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        prime_window(base_url, fdsn_cfg, station, channels, res["start"], res["end"])
        verify_fully_cached(base_url, fdsn_cfg, station, channels, res["start"],
                             res["end"], f"{scn_id}/{station} CACHED (pre-measure)")
        windows[station] = res

    for station in uncached_stations:
        res = resolve_uncached_window(
            base_url, fdsn_cfg, station, channels, fdsn_cfg["target_date"]
        )
        print(f"[INFO] {scn_id}: station={station} role=UNCACHED "
              f"channels={channels} date={res['date']}"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        windows[station] = res

    def measure():
        for station in cached_stations:
            res = windows[station]
            _fdsn_call_all(base_url, fdsn_cfg, [station], res["start"], res["end"],
                            channels)
        for station in uncached_stations:
            res = windows[station]
            _fdsn_call_all(base_url, fdsn_cfg, [station], res["start"], res["end"],
                            channels)

    def cleanup():
        for station in uncached_stations:
            res = windows[station]
            verify_fully_cached(base_url, fdsn_cfg, station, channels, res["start"],
                                 res["end"], f"{scn_id}/{station} (post-measure)")

    return measure, cleanup


# --------------------------------------------------------------------------
# 5 skenario yang diuji — id dipertahankan sama dengan kind di
# ram_cpu_benchmark.py/scenarios.json supaya mudah dibandingkan, label
# dihitung dinamis dari jumlah stasiun aktual (TIDAK hardcode).
# --------------------------------------------------------------------------

def build_scenarios(stations):
    n = len(stations)
    cached_grp, uncached_grp = (
        split_mixed_stations(stations) if n >= 2 else (stations, [])
    )
    return [
        {
            "id": "fdsn_cached",
            "label": f"FDSN Cached ({n} stasiun: {', '.join(stations)})",
            "prepare": lambda base_url, fdsn_cfg:
                prepare_fdsn_cached(base_url, fdsn_cfg, stations, "fdsn_cached"),
        },
        {
            "id": "fdsn_uncached",
            "label": f"FDSN Uncached ({n} stasiun: {', '.join(stations)})",
            "prepare": lambda base_url, fdsn_cfg:
                prepare_fdsn_uncached(base_url, fdsn_cfg, stations, "fdsn_uncached"),
        },
        {
            "id": "fdsn_multi_cached",
            "label": f"FDSN Multi Cached ({n} stasiun: {', '.join(stations)})",
            "prepare": lambda base_url, fdsn_cfg:
                prepare_fdsn_cached(base_url, fdsn_cfg, stations, "fdsn_multi_cached"),
        },
        {
            "id": "fdsn_multi_uncached",
            "label": f"FDSN Multi Uncached ({n} stasiun: {', '.join(stations)})",
            "prepare": lambda base_url, fdsn_cfg:
                prepare_fdsn_uncached(base_url, fdsn_cfg, stations, "fdsn_multi_uncached"),
        },
        {
            "id": "fdsn_multi_mixed",
            "label": (
                f"FDSN Mixed ({len(cached_grp)} cached + "
                f"{len(uncached_grp)} uncached)"
            ),
            "prepare": lambda base_url, fdsn_cfg:
                prepare_fdsn_mixed(base_url, fdsn_cfg, stations, "fdsn_multi_mixed"),
        },
    ]


# --------------------------------------------------------------------------
# Eksekusi + pengukuran — flow IDENTIK dengan run_scenario() di
# ram_cpu_benchmark.py (baseline window, measured window, stable
# window), supaya angkanya bisa dibandingkan apple-to-apple.
# --------------------------------------------------------------------------

def run_scenario(base_url, scn, fdsn_cfg, server, restart_between):
    if restart_between:
        pid = server.restart()
    else:
        pid = server.current_pid()

    status = "OK"
    measure_fn = None
    cleanup_fn = lambda: None
    try:
        measure_fn, cleanup_fn = scn["prepare"](base_url, fdsn_cfg)
    except Exception as exc:  # noqa: BLE001
        status = f"FAILED (prepare): {exc}"

    sampler = Sampler(pid)
    sampler.start()

    time.sleep(BASELINE_WINDOW_SEC)
    t_before_start = time.time() - BASELINE_WINDOW_SEC
    t_before_end = time.time()
    before_samples = sampler.samples_between(t_before_start, t_before_end)
    ram_before = mean([s[1] for s in before_samples])

    t_req_start = time.time()
    if measure_fn is not None:
        try:
            measure_fn()
        except Exception as exc:  # noqa: BLE001
            status = f"FAILED: {exc}"
    t_req_end = time.time()

    try:
        cleanup_fn()
    except Exception as exc:  # noqa: BLE001
        if status == "OK":
            status = f"FAILED (post-verify): {exc}"

    time.sleep(STABLE_WAIT_SEC)
    t_stable_start = time.time() - STABLE_WINDOW_SEC
    t_stable_end = time.time()
    stable_samples = sampler.samples_between(t_stable_start, t_stable_end)
    ram_stable = mean([s[1] for s in stable_samples])

    window_samples = sampler.samples_between(t_req_start, t_req_end)
    ram_average = mean([s[1] for s in window_samples]) if window_samples else ram_before
    ram_peak = max([s[1] for s in window_samples], default=ram_before)
    cpu_average = mean([s[2] for s in window_samples]) if window_samples else 0.0
    cpu_peak = max([s[2] for s in window_samples], default=0.0)

    sampler.stop()

    result = {
        "scenario": scn["id"],
        "label": scn["label"],
        "ram_before_mb": round(ram_before, 2),
        "ram_average_mb": round(ram_average, 2),
        "ram_peak_mb": round(ram_peak, 2),
        "ram_stable_mb": round(ram_stable, 2),
        "delta_ram_mb": round(ram_stable - ram_before, 2),
        "cpu_average_pct": round(cpu_average, 2),
        "cpu_peak_pct": round(cpu_peak, 2),
        "duration_sec": round(t_req_end - t_req_start, 3),
        "status": status,
    }
    raw_timeseries = [
        {"t": t, "rss_mb": round(rss, 2), "cpu_pct": round(cpu, 2)}
        for t, rss, cpu in sampler.all_samples()
    ]
    return result, raw_timeseries


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--spawn", help='Perintah start server, mis. "uvicorn app.main:app --port 8000"')
    parser.add_argument("--attach-pid", type=int, help="PID server yang sudah berjalan (mode attach)")
    parser.add_argument("--no-restart", action="store_true", help="Jangan restart server antar-skenario")
    parser.add_argument("--cwd", default=str(BENCH_DIR.parent), help="Working dir untuk --spawn")
    parser.add_argument("--out-prefix", default=None, help="Prefix nama file output (default: timestamp)")
    parser.add_argument(
        "--stations", nargs="+", required=True,
        help=(
            "Daftar stasiun FDSN yang diuji ULANG, WAJIB diisi, 1-5 "
            "stasiun, mis. --stations AAFM AAI. Jumlah & nama station "
            "yang benar-benar dites persis mengikuti argumen ini."
        ),
    )
    parser.add_argument(
        "--date", default=None,
        help=(
            "Override target_date FDSN (format YYYY-MM-DD). Resolver "
            "tetap mundur otomatis kalau tanggal ini sudah cached."
        ),
    )
    args = parser.parse_args()

    if not args.spawn and not args.attach_pid:
        parser.error("Wajib salah satu: --spawn '<cmd>' atau --attach-pid <pid>")

    stations = args.stations
    if not (MIN_STATIONS <= len(stations) <= MAX_STATIONS):
        parser.error(
            f"--stations harus berisi {MIN_STATIONS}-{MAX_STATIONS} "
            f"stasiun, diberikan {len(stations)}: {stations}"
        )

    # fdsn.network/location/channels/max_lookback_days/max_points
    # dibaca dari scenarios.json (read-only, TIDAK ditulis ulang) —
    # HANYA untuk parameter koneksi, BUKAN untuk daftar stasiun.
    # Daftar stasiun aktual SELALU 100% dari --stations, sesuai
    # permintaan ("jangan ada hardcode 1/4 station atau AAFM saja").
    scenarios_cfg = json.loads(SCENARIOS_PATH.read_text())
    fdsn_json = scenarios_cfg["fdsn"]
    fdsn_cfg = {
        "network": fdsn_json["network"],
        "location": fdsn_json["location"],
        "channels": fdsn_json["channels"],
        "max_lookback_days": fdsn_json.get("max_lookback_days", 30),
        "max_points": fdsn_json.get("max_points"),
    }
    fdsn_cfg["target_date"] = args.date or default_target_date()

    print(f"[CONFIG] FDSN stations={stations} (n={len(stations)}) "
          f"channels={fdsn_cfg['channels']} "
          f"target_date={fdsn_cfg['target_date']} "
          f"({'override --date' if args.date else 'otomatis: kemarin, lokal'})\n")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = args.out_prefix or time.strftime("%Y%m%d_%H%M%S")

    server = ServerHandle(spawn_cmd=args.spawn, attach_pid=args.attach_pid, cwd=args.cwd)
    if not args.attach_pid:
        server.start()

    restart_between = not args.no_restart and not args.attach_pid

    scenarios = build_scenarios(stations)

    all_results = []
    all_raw = {}

    try:
        for scn in scenarios:
            print(f"[RUN] {scn['id']} - {scn['label']}")
            result, raw = run_scenario(args.base_url, scn, fdsn_cfg, server, restart_between)
            print(
                f"      status={result['status']} "
                f"ram_avg={result['ram_average_mb']}MB "
                f"ram_peak={result['ram_peak_mb']}MB "
                f"delta_ram={result['delta_ram_mb']}MB "
                f"cpu_avg={result['cpu_average_pct']}% "
                f"cpu_peak={result['cpu_peak_pct']}% "
                f"duration={result['duration_sec']}s"
            )
            all_results.append(result)
            all_raw[scn["id"]] = raw
    finally:
        if not args.attach_pid:
            server.stop()

    csv_path = RESULTS_DIR / f"{run_id}_fdsn_cache_summary.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scenario", "label", "ram_before_mb", "ram_average_mb",
                "ram_peak_mb", "ram_stable_mb", "delta_ram_mb",
                "cpu_average_pct", "cpu_peak_pct",
                "duration_sec", "status",
            ],
        )
        writer.writeheader()
        writer.writerows(all_results)

    raw_path = RESULTS_DIR / f"{run_id}_fdsn_cache_raw_timeseries.json"
    raw_path.write_text(json.dumps(all_raw, indent=2))

    print(f"\nSummary CSV : {csv_path}")
    print(f"Raw timeseries JSON : {raw_path}")


if __name__ == "__main__":
    main()