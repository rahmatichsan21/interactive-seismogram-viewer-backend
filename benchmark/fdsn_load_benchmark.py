"""
Benchmark KHUSUS untuk FDSN Load — cold (uncached) vs warm (cached) vs
mixed, memakai endpoint GET /api/waveform PERSIS seperti yang dipakai
frontend (src/api/waveformApi.js:getWaveform()):
    params: network, station, location, channel, start_time, end_time,
            max_points

TIDAK menjalankan processing/filter/instrument-correction/PSD/HVSR.
TIDAK mengubah benchmark/ram_cpu_benchmark.py atau kode backend.

== Temuan yang mendasari desain script ini (lihat juga penjelasan di chat) ==
1. Frontend SELALU kirim max_points=75000 (bukan 150000) — lihat
   src/api/waveformApi.js: `export const MAX_POINTS = 75000`.
2. Channel WILDCARD ("SH*") memicu _expand_channel_wildcard() di
   app/services/waveform_provider_service.py -> 1 request FDSN
   inventory tambahan + N_window x N_channel panggilan
   client.get_waveforms() sekuensial (mis. 24 window x 3 channel =
   72 panggilan network untuk 1 hari data) -> ini penyebab utama
   timeout 300s pada benchmark lama, BUKAN bug kode. Frontend asli
   pun mengirim SATU channel konkret (hasil pilih user), bukan
   wildcard -> script ini default channel konkret tunggal.
3. Retry math dari app/services/waveform_service.py:
   MAX_DOWNLOAD_ATTEMPTS(3) x FDSN_TIMEOUT_SECONDS(20)
   + 2 x RETRY_DELAY_SECONDS(2) ~= 64 detik/window terburuk.
   Untuk N window per request, worst-case ~= N x 64s -> dasar
   perhitungan REQUEST_TIMEOUT_SEC & WINDOW_HOURS di CONFIG di bawah.
4. HTTP 500 di GET /api/waveform HANYA berasal dari `except Exception`
   generik di app/routers/waveform.py (baris ~101-109) — script ini
   selalu menampilkan body/detail response apa adanya per station,
   tidak menyembunyikan.
5. Cache waveform FDSN bersifat PERSISTEN (disk+MySQL, per jam UTC,
   key = network/station/location/channel) — BUKAN TTL. Artinya:
   - "cached/warm" = window yang SUDAH pernah diminta (di-prime dulu
     di script ini, untimed, sebelum window diukur).
   - "uncached/cold" = window yang BELUM PERNAH diminta di database
     ini. Sekali sukses diminta, ia PERMANEN ter-cache. Untuk run
     ulang yang benar-benar cold lagi, ganti tanggal COLD_* di
     CONFIG ke tanggal yang belum pernah dipakai.

Cara pakai (2 terminal, sama seperti benchmark lama):
  Terminal 1:
    uvicorn app.main:app --host 127.0.0.1 --port 8000
  Terminal 2:
    python benchmark/fdsn_load_benchmark.py --attach-pid <PID>
"""

import argparse
import csv
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import psutil

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"

SAMPLE_INTERVAL_SEC = 0.2
BASELINE_WINDOW_SEC = 1.5
STABLE_WAIT_SEC = 2.0
STABLE_WINDOW_SEC = 1.5

# ---------------------------------------------------------------------
# CONFIG — sesuaikan di sini, TANPA perlu scenarios.json terpisah.
# ---------------------------------------------------------------------
CONFIG = {
    "base_url": "http://127.0.0.1:8000",
    "network": "IA",
    "location": "*",
    # Channel KONKRET tunggal, meniru pola pemakaian frontend asli
    # (bukan wildcard "SH*" — lihat catatan #2 di docstring atas).
    "channel": "SHZ",
    "stations": ["AAI", "ABJI", "ABSM", "ACJM"],

    # Durasi window uji (jam). 2 jam = maksimum 2 window cache/station.
    # Worst-case (semua window gagal+retry) ~= window_hours x 64s per
    # station (lihat catatan #3). Naikkan dengan hati-hati.
    "window_hours": 2,

    # Window waktu untuk skenario CACHED (di-prime dulu, lalu diukur
    # lagi -> dijamin cache hit). Boleh tanggal apa saja yang valid
    # ada datanya di BMKG untuk station-station di atas.
    "warm_start_time": "2025-07-01T00:00:00",

    # 3 window COLD TERPISAH — supaya scenario 1, 3, dan separuh
    # scenario 4 tidak saling mencemari status cache-nya. WAJIB ganti
    # ke tanggal yang BELUM PERNAH diminta kalau ingin re-run yang
    # benar2 cold lagi.
    "cold_start_time_1station": "2026-09-06T00:00:00",
    "cold_start_time_4station": "2026-09-06T00:00:00",
    "cold_start_time_mixed": "2026-09-07T00:00:00",

    # Timeout per-HTTP-request (detik). Dihitung dari retry math
    # (catatan #3), BUKAN 300 — supaya gagal lebih cepat terdeteksi.
    "request_timeout_sec": 200,

    # Persis default frontend (src/api/waveformApi.js: MAX_POINTS).
    "max_points": 75000,
}


def end_time_from(start_iso, hours):
    start = datetime.fromisoformat(start_iso)
    return (start + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------
# HTTP helper (stdlib only, sama pola dengan ram_cpu_benchmark.py)
# ---------------------------------------------------------------------

def http_get_waveform(base_url, cfg, network, station, location, channel,
                       start_time, end_time, max_points, timeout):
    """GET /api/waveform — param & urutan PERSIS
    src/api/waveformApi.js:getWaveform(). Return (status, detail_or_None).
    detail_or_None berisi body response (untuk sukses: dict hasil
    stream_to_json; untuk gagal: apa adanya dari FastAPI HTTPException
    detail, TIDAK disembunyikan)."""
    params = {
        "network": network,
        "station": station,
        "location": location,
        "channel": channel,
        "start_time": start_time,
        "end_time": end_time,
    }
    if max_points:
        params["max_points"] = max_points
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{base_url}/api/waveform?{qs}"
    req = urllib.request.Request(url, method="GET")
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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Socket timeout / connection error -> gagal cepat, bukan
        # nunggu library retry internal lain (yang memang sudah
        # dibatasi via `timeout` di atas).
        return None, f"CONNECTION/TIMEOUT ERROR: {exc}"


def call_station(base_url, cfg, station, start_time, end_time):
    """Panggil satu station. Return dict {station, ok, status, detail}."""
    status, detail = http_get_waveform(
        base_url, cfg,
        network=cfg["network"],
        station=station,
        location=cfg["location"],
        channel=cfg["channel"],
        start_time=start_time,
        end_time=end_time,
        max_points=cfg["max_points"],
        timeout=cfg["request_timeout_sec"],
    )
    ok = status == 200
    return {"station": station, "ok": ok, "status": status, "detail": detail}


def call_stations(base_url, cfg, stations, start_time, end_time):
    """Panggil beberapa station SATU PER SATU (sekuensial, sama seperti
    frontend memuat trace demi trace). Setiap station gagal TIDAK
    menghentikan station lain — semua dicoba, hasil per-station
    dikumpulkan untuk pelaporan."""
    results = []
    for station in stations:
        results.append(call_station(base_url, cfg, station, start_time, end_time))
    return results


def summarize_station_results(results):
    failed = [r for r in results if not r["ok"]]
    if not failed:
        return "OK"
    parts = []
    for r in failed:
        status_label = r["status"] if r["status"] is not None else "NO-RESPONSE"
        detail = r["detail"]
        if isinstance(detail, dict):
            detail = detail.get("detail", detail)
        parts.append(f"{r['station']}=HTTP {status_label} ({detail})")
    return "FAILED: " + "; ".join(parts)


# ---------------------------------------------------------------------
# RAM/CPU sampler — SAMA persis dengan versi yang sudah diperbaiki di
# ram_cpu_benchmark.py (cache objek Process per-PID supaya baseline
# cpu_percent() psutil tidak hilang setiap tick / tidak "107.8% terus").
# Diduplikasi di sini (bukan di-import) supaya script ini berdiri
# sendiri, sesuai instruksi "jangan ubah ram_cpu_benchmark.py".
# ---------------------------------------------------------------------

class Sampler:
    def __init__(self, pid):
        self.proc = psutil.Process(pid)
        self._proc_cache = {pid: self.proc}
        self.proc.cpu_percent(interval=None)  # priming, hasil diabaikan

        self._stop = threading.Event()
        self._samples = []  # (timestamp, rss_mb, cpu_pct)
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
                    child.cpu_percent(interval=None)  # priming
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


# ---------------------------------------------------------------------
# Skenario — masing2 SELF-CONTAINED (mengurus priming sendiri kalau
# perlu), supaya urutan menjalankan ke-4 skenario TIDAK saling
# bergantung.
# ---------------------------------------------------------------------

def prepare_1station_uncached(base_url, cfg):
    station = cfg["stations"][0]
    start = cfg["cold_start_time_1station"]
    end = end_time_from(start, cfg["window_hours"])

    def measure():
        results = call_stations(base_url, cfg, [station], start, end)
        return summarize_station_results(results)

    return measure, (lambda: None)


def prepare_4station_cached(base_url, cfg):
    stations = cfg["stations"]
    start = cfg["warm_start_time"]
    end = end_time_from(start, cfg["window_hours"])

    # Priming — untimed, di luar window Sampler (dipanggil sebelum
    # Sampler dibuat, lihat run_scenario()).
    call_stations(base_url, cfg, stations, start, end)

    def measure():
        results = call_stations(base_url, cfg, stations, start, end)
        return summarize_station_results(results)

    return measure, (lambda: None)


def prepare_4station_uncached(base_url, cfg):
    stations = cfg["stations"]
    start = cfg["cold_start_time_4station"]
    end = end_time_from(start, cfg["window_hours"])

    def measure():
        results = call_stations(base_url, cfg, stations, start, end)
        return summarize_station_results(results)

    return measure, (lambda: None)


def prepare_2cached_2uncached(base_url, cfg):
    stations = cfg["stations"]
    half = len(stations) // 2
    cached_stations = stations[:half]
    uncached_stations = stations[half:]

    warm_start = cfg["warm_start_time"]
    warm_end = end_time_from(warm_start, cfg["window_hours"])
    cold_start = cfg["cold_start_time_mixed"]
    cold_end = end_time_from(cold_start, cfg["window_hours"])

    # Prime HANYA separuh yang harus "cached" — separuh uncached
    # sengaja TIDAK di-prime.
    call_stations(base_url, cfg, cached_stations, warm_start, warm_end)

    def measure():
        r1 = call_stations(base_url, cfg, cached_stations, warm_start, warm_end)
        r2 = call_stations(base_url, cfg, uncached_stations, cold_start, cold_end)
        return summarize_station_results(r1 + r2)

    return measure, (lambda: None)


SCENARIOS = [
    {
        "id": "fdsn_1station_uncached",
        "label": "FDSN 1 station - uncached",
        "prepare": prepare_1station_uncached,
    },
    {
        "id": "fdsn_4station_cached",
        "label": "FDSN 4 station - all cached",
        "prepare": prepare_4station_cached,
    },
    {
        "id": "fdsn_4station_uncached",
        "label": "FDSN 4 station - all uncached",
        "prepare": prepare_4station_uncached,
    },
    {
        "id": "fdsn_2cached_2uncached",
        "label": "FDSN 2 cached + 2 uncached",
        "prepare": prepare_2cached_2uncached,
    },
]


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def run_scenario(base_url, cfg, scn, pid):
    status = "OK"
    measure_fn = None
    cleanup_fn = lambda: None
    try:
        measure_fn, cleanup_fn = scn["prepare"](base_url, cfg)
    except Exception as exc:  # noqa: BLE001
        status = f"FAILED (prepare): {exc}"

    sampler = Sampler(pid)
    sampler.start()

    time.sleep(BASELINE_WINDOW_SEC)
    t_before_start = time.time() - BASELINE_WINDOW_SEC
    t_before_end = time.time()
    ram_before = mean([s[1] for s in sampler.samples_between(t_before_start, t_before_end)])

    t_req_start = time.time()
    if measure_fn is not None:
        try:
            scenario_status = measure_fn()
            if scenario_status != "OK":
                status = scenario_status
        except Exception as exc:  # noqa: BLE001
            status = f"FAILED: {exc}"
    t_req_end = time.time()

    try:
        cleanup_fn()
    except Exception:  # noqa: BLE001
        pass

    time.sleep(STABLE_WAIT_SEC)
    t_stable_start = time.time() - STABLE_WINDOW_SEC
    t_stable_end = time.time()
    ram_stable = mean([s[1] for s in sampler.samples_between(t_stable_start, t_stable_end)])

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
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=CONFIG["base_url"])
    parser.add_argument("--attach-pid", type=int, required=True,
                         help="PID proses uvicorn yang sudah berjalan (Terminal 1)")
    parser.add_argument("--out-prefix", default=None)
    args = parser.parse_args()

    cfg = dict(CONFIG)
    cfg["base_url"] = args.base_url

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = args.out_prefix or time.strftime("%Y%m%d_%H%M%S")

    print(f"Stations: {cfg['stations']}")
    print(f"Channel : {cfg['channel']} (konkret, bukan wildcard)")
    print(f"Window  : {cfg['window_hours']} jam per scenario")
    print(f"Timeout : {cfg['request_timeout_sec']}s per HTTP call\n")

    all_results = []
    for scn in SCENARIOS:
        print(f"[RUN] {scn['id']} - {scn['label']}")
        result = run_scenario(args.base_url, cfg, scn, args.attach_pid)
        print(
            f"      status={result['status']}\n"
            f"      ram_avg={result['ram_average_mb']}MB "
            f"ram_peak={result['ram_peak_mb']}MB "
            f"delta_ram={result['delta_ram_mb']}MB "
            f"cpu_avg={result['cpu_average_pct']}% "
            f"cpu_peak={result['cpu_peak_pct']}% "
            f"duration={result['duration_sec']}s"
        )
        all_results.append(result)

    csv_path = RESULTS_DIR / f"{run_id}_fdsn_load_summary.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scenario", "label", "ram_before_mb", "ram_average_mb",
                "ram_peak_mb", "ram_stable_mb", "delta_ram_mb",
                "cpu_average_pct", "cpu_peak_pct", "duration_sec", "status",
            ],
        )
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nSummary CSV: {csv_path}")


if __name__ == "__main__":
    main()