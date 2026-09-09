"""
Milestone 10 — Automated RAM/CPU benchmark.

Menjalankan 22 skenario (13 skenario dasar Milestone 10 + 9 skenario
lanjutan: FDSN cached/uncached/multi/mixed, Spectrogram, PSD cold/warm,
HVSR) lewat endpoint backend YANG SUDAH ADA:
  GET    /api/waveform                 (FDSN)
  GET    /api/waveform/status          (FDSN — cek cache, read-only)
  POST   /api/upload/miniseed          (Local Upload)
  POST   /api/upload/stationxml        (Local Upload, opsional/PSD/HVSR)
  GET    /api/upload/{session_id}/waveform
  POST   /process                      (Trim/Filter/Instrument Correction)
  GET    /api/spectrogram              (Spectrogram)
  GET    /api/psd                      (PSD, cache RAM via psd_cache)
  GET    /api/hvsr                     (HVSR)
  DELETE /api/upload/{session_id}      (reset Local session)

TIDAK mengubah kode aplikasi apapun — murni memanggil API dari luar dan
mengukur RSS + CPU proses backend via psutil.

== FDSN modular multi-station (5 skenario fdsn_*) ==
Channel SELALU dikirim konkret satu-satu dari `fdsn.channels` (mis.
SHZ/SHE/SHN) — TIDAK PERNAH wildcard "SH*". Window SELALU 24 jam penuh
dari `fdsn.target_date`. `target_date` SELALU dihitung otomatis =
tanggal KEMARIN (waktu lokal komputer yang menjalankan script), TIDAK
PERNAH hari ini dan TIDAK di-hardcode — override manual lewat --date.
Stasiun yang dipakai diatur oleh
`fdsn.stations` (default 5, override via --stations).

Status cached/uncached SELALU diverifikasi live lewat GET
/api/waveform/status per (stasiun, channel) — TIDAK PERNAH diasumsikan.
Kalau `target_date` ternyata sudah (sebagian) ter-cache untuk suatu
stasiun, resolver mundur ke date-1, date-2, dst. sampai menemukan
window yang benar-benar uncached di SEMUA channel stasiun itu — cache
waveform persisten (disk+DB), bukan TTL, jadi ini WAJIB, bukan opsional.
Lihat `resolve_uncached_window()`.

Cara pakai (lihat juga bagian "Cara menjalankan" di laporan):
  # Mode A - script yang menjalankan/mengelola server (uvicorn):
  python benchmarks/ram_cpu_benchmark.py \
      --spawn "uvicorn app.main:app --host 127.0.0.1 --port 8000" \
      --base-url http://127.0.0.1:8000

  # Mode B - attach ke server yang SUDAH berjalan (dev server Anda sendiri):
  python benchmarks/ram_cpu_benchmark.py \
      --attach-pid 12345 \
      --base-url http://127.0.0.1:8000 \
      --no-restart

  # Subset station FDSN (default: 5 station di scenarios.json):
  python benchmarks/ram_cpu_benchmark.py --attach-pid 12345 --no-restart \
      --stations AAFM AAI

  # Override target date FDSN (default: OTOMATIS = kemarin, lokal):
  python benchmarks/ram_cpu_benchmark.py --attach-pid 12345 --no-restart \
      --date 2026-09-10
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
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


# --------------------------------------------------------------------------
# HTTP helpers (stdlib only — tidak menambah dependency selain psutil)
# --------------------------------------------------------------------------

def http_json(method, url, payload=None, timeout=300):
    data = None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
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


def http_upload_file(url, field_name, file_path, extra_fields=None, timeout=300):
    """Multipart upload tanpa dependency `requests` (stdlib only)."""
    boundary = uuid.uuid4().hex
    file_path = Path(file_path)
    body = bytearray()

    def add_field(name, value):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        body.extend(f"{value}\r\n".encode())

    for name, value in (extra_fields or {}).items():
        add_field(name, value)

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{file_path.name}"\r\n'
        ).encode()
    )
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            detail = json.loads(body_bytes)
        except Exception:
            detail = body_bytes.decode("utf-8", errors="replace")
        return exc.code, detail


# --------------------------------------------------------------------------
# RAM/CPU sampler
# --------------------------------------------------------------------------

class Sampler:
    """Sampling RSS (MB) + CPU% proses backend (termasuk child process)
    setiap SAMPLE_INTERVAL_SEC, berjalan di background thread.

    CATATAN PENTING soal CPU% (bug lama & klarifikasi semantik):
    - `psutil.Process.cpu_percent(interval=None)` HANYA akurat kalau
      dipanggil berulang pada objek Process YANG SAMA (psutil menyimpan
      baseline waktu CPU internal di objek itu). Kode versi sebelumnya
      memanggil `self.proc.children(recursive=True)` di SETIAP tick,
      yang membuat objek `Process` BARU untuk child setiap kali —
      baseline-nya selalu hilang, sehingga `cpu_percent()` untuk child
      jadi tidak berarti (sering 0.0 di awal proses, atau angka yang
      tampak "konstan"/acak karena dihitung sejak process start, bukan
      sejak tick sebelumnya). Ini yang menyebabkan CPU Peak tampak
      selalu sama (mis. 107.8%) di semua skenario, tidak merefleksikan
      beban nyata. FIX: cache objek Process per-PID, dipakai ulang
      antar tick; hanya PID baru yang dibuat objek baru (dan di-prime
      dulu, hasil primingnya diabaikan sesuai aturan psutil).
    - Angka CPU% dari psutil TIDAK dinormalisasi ke jumlah core:
      100% = 1 core penuh terpakai. Untuk proses yang memakai banyak
      thread (mis. numpy/scipy/ObsPy lewat BLAS multi-thread), nilai
      >100% (mis. 150% = 1.5 core) adalah SAH, bukan bug. Nilai
      "selalu sama di semua skenario" itulah tanda bug (di atas),
      bukan sekadar nilai >100%.
    """

    def __init__(self, pid):
        self.proc = psutil.Process(pid)
        # dict pid -> psutil.Process, supaya objek yang SAMA dipakai
        # ulang antar tick (baseline cpu_percent tidak hilang).
        self._proc_cache = {pid: self.proc}
        self.proc.cpu_percent(interval=None)  # priming, hasil diabaikan

        self._stop = threading.Event()
        self._samples = []  # list of (timestamp, rss_mb, cpu_pct)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _all_procs(self):
        """Refresh daftar child PID, tapi PERTAHANKAN objek Process
        yang sudah ada (jangan buat ulang) supaya baseline cpu_percent
        tetap valid antar tick. PID yang sudah mati dibuang dari cache."""
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
                    # Prime child baru: panggilan pertama cpu_percent()
                    # meaningless (aturan psutil) — sengaja diabaikan
                    # supaya tick BERIKUTNYA baru dianggap valid.
                    child.cpu_percent(interval=None)
                except psutil.Error:
                    pass

        # Buang PID yang sudah tidak ada lagi.
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
# Server lifecycle
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
        # Beri waktu server siap. Untuk kebutuhan nyata, ganti dengan
        # polling endpoint kesehatan (mis. GET /docs) sampai 200.
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


# --------------------------------------------------------------------------
# Scenario execution
# --------------------------------------------------------------------------

def run_fdsn_load_multi(base_url, cfg, sampler):
    fdsn = cfg["fdsn"]
    start, end = _day_range(fdsn["target_date"])
    _fdsn_call_all(base_url, cfg, [fdsn["stations"][0]], start, end)


def default_target_date():
    """Tanggal kalender KEMARIN menurut waktu lokal komputer yang
    menjalankan script ini (BUKAN hari ini, BUKAN hardcoded). Dipakai
    sebagai default fdsn.target_date supaya benchmark tidak pernah
    diam-diam mengetes window "hari ini" yang datanya mungkin belum
    lengkap terkirim ke FDSN. `resolve_uncached_window()` tetap boleh
    mundur lebih jauh lagi (kemarin-1, kemarin-2, dst.) kalau tanggal
    ini ternyata sudah cached — tapi TIDAK PERNAH maju ke hari ini."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _qs(params):
    return "&".join(
        f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v is not None
    )


def _day_range(date_str, window_hours=24):
    """'YYYY-MM-DD' -> (start_iso, end_iso) untuk window N jam penuh
    (default 24 jam), UTC-aligned di 00:00."""
    start = datetime.fromisoformat(date_str + "T00:00:00")
    end = start + timedelta(hours=window_hours)
    return start.isoformat(), end.isoformat()


def check_waveform_cached(base_url, cfg, station, channel, start_time, end_time):
    """GET /api/waveform/status — read-only, TIDAK mengisi cache.
    Return True kalau window (station, channel, start, end) SUDAH
    fully cached (download_needed=False)."""
    fdsn = cfg["fdsn"]
    params = {
        "network": fdsn["network"],
        "station": station,
        "location": fdsn["location"],
        "channel": channel,
        "start_time": start_time,
        "end_time": end_time,
    }
    status, resp = http_json("GET", f"{base_url}/api/waveform/status?{_qs(params)}")
    if status != 200:
        raise RuntimeError(
            f"GET /api/waveform/status gagal untuk {station}.{channel}: "
            f"HTTP {status} {resp}"
        )
    return not resp["download_needed"]


def resolve_uncached_window(base_url, cfg, station, channels=None, start_date=None):
    """
    Cari window 24-jam yang BENAR-BENAR uncached (download_needed=True
    di SEMUA channel) untuk `station`, mulai dari `start_date` (default
    fdsn.target_date) mundur ke date-1, date-2, dst. kalau tanggal
    tersebut ternyata sudah (sebagian) ter-cache.

    Status dicek LIVE per (station, channel) lewat GET
    /api/waveform/status — TIDAK PERNAH diasumsikan dari cache lokal
    script ini, karena cache waveform backend persisten (disk+DB),
    bukan TTL: sekali sebuah tanggal pernah diminta, ia AKAN selalu
    cached untuk run-run berikutnya.

    Return dict: {"date", "start", "end", "reason", "cached_before"}
    - "cached_before": True kalau start_date awal (target_date) SUDAH
      cached (dipakai untuk pesan info "kenapa tanggal dipindah").
    """
    fdsn = cfg["fdsn"]
    channels = channels or fdsn["channels"]
    start_date = start_date or fdsn["target_date"]
    max_lookback = fdsn.get("max_lookback_days", 30)

    date = datetime.fromisoformat(start_date)
    reason = f"target date {start_date} belum ter-cache untuk semua channel"
    cached_before = False

    for _ in range(max_lookback):
        date_str = date.strftime("%Y-%m-%d")
        start, end = _day_range(date_str)
        status_map = {
            ch: check_waveform_cached(base_url, cfg, station, ch, start, end)
            for ch in channels
        }
        if not any(status_map.values()):
            # Tidak satu channel pun cached -> window ini genuinely uncached.
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
        "ter-cache — perluas fdsn.max_lookback_days kalau ini memang "
        "diharapkan."
    )


def prime_window(base_url, cfg, station, channels, start, end):
    """Panggil /api/waveform untuk semua channel sekali (untimed) agar
    window benar-benar fully cached. Idempotent: kalau sebagian/semua
    channel sudah cached (mis. karena scenario lain sudah men-download
    window yang sama), panggilan ini tetap aman (cache hit)."""
    _fdsn_call_all(base_url, cfg, [station], start, end, channels=channels)


def verify_fully_cached(base_url, cfg, station, channels, start, end, context):
    """Assert semua channel benar2 fully cached SETELAH sebuah request
    — dipanggil dari cleanup_fn (untimed) supaya tidak ikut mengotori
    RAM/CPU measurement. Cetak hasil verifikasi, raise kalau gagal
    (partial download tidak boleh dianggap sukses diam-diam)."""
    status_map = {
        ch: check_waveform_cached(base_url, cfg, station, ch, start, end)
        for ch in channels
    }
    not_cached = [ch for ch, ok in status_map.items() if not ok]
    if not_cached:
        raise RuntimeError(
            f"[{context}] Verifikasi pasca-request GAGAL: {station} "
            f"channel {not_cached} @ {start}->{end} MASIH "
            "download_needed=True (kemungkinan ada window/jendela jam "
            "yang gagal di-download parsial)."
        )
    print(f"      [VERIFY] {context}: {station} @ {start}->{end} "
          "FULLY CACHED untuk semua channel.")


def _fdsn_call_all(base_url, cfg, stations, start_time, end_time, channels=None):
    """Panggil GET /api/waveform untuk setiap (station, channel) di
    `stations` x `channels`, pakai rentang waktu `start_time`/
    `end_time` yang diberikan. Channel SELALU konkret satu-satu (dari
    fdsn.channels) — TIDAK PERNAH wildcard "SH*". Dipakai bareng oleh
    skenario base, cached, uncached, multi, dan mixed — supaya logika
    permintaan HTTP-nya konsisten satu tempat."""
    fdsn = cfg["fdsn"]
    channels = channels or fdsn["channels"]
    for station in stations:
        for channel in channels:
            params = {
                "network": fdsn["network"],
                "station": station,
                "location": fdsn["location"],
                "channel": channel,
                "start_time": start_time,
                "end_time": end_time,
            }
            if fdsn.get("max_points"):
                params["max_points"] = fdsn["max_points"]
            status, resp = http_json(
                "GET", f"{base_url}/api/waveform?{_qs(params)}"
            )
            if status != 200:
                raise RuntimeError(
                    f"FDSN load {station}.{channel} failed: HTTP {status} {resp}"
                )


def upload_local(base_url, cfg):
    local = cfg["local"]
    status, resp = http_upload_file(
        f"{base_url}/api/upload/miniseed", "file", local["miniseed_path"]
    )
    if status != 200:
        raise RuntimeError(f"Local upload failed: HTTP {status} {resp}")
    session_id = resp["session_id"]

    stationxml = local.get("stationxml_path")
    if stationxml and Path(stationxml).exists():
        status, resp2 = http_upload_file(
            f"{base_url}/api/upload/stationxml",
            "file",
            stationxml,
            extra_fields={"session_id": session_id},
        )
        if status != 200:
            raise RuntimeError(f"StationXML upload failed: HTTP {status} {resp2}")

    status, wf = http_json(
        "GET", f"{base_url}/api/upload/{session_id}/waveform"
    )
    if status != 200 or not wf.get("traces"):
        raise RuntimeError(f"Fetch upload waveform failed: HTTP {status} {wf}")

    first_trace = wf["traces"][0]
    trace_meta = {
        "network": first_trace.get("network") or "XX",
        "station": wf.get("station") or "STA",
        "location": first_trace.get("location") or "--",
        "channel": first_trace.get("channel"),
        "start_time": first_trace["time"][0],
        "end_time": first_trace["time"][-1],
    }
    return session_id, trace_meta


def run_local_upload_only(base_url, cfg, sampler):
    session_id, _ = upload_local(base_url, cfg)
    status, _ = http_json("DELETE", f"{base_url}/api/upload/{session_id}")
    if status != 200:
        raise RuntimeError(f"DELETE session failed: HTTP {status}")


def _parse_iso(ts):
    """Parse ISO datetime string dari response backend (mis. dari
    ObsPy UTCDateTime.isoformat()) secara aman lintas versi Python."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def resolve_trim_placeholders(operations, meta):
    """Ganti token __DATA_START__/__DATA_MID__ pada operasi trim
    dengan waktu ASLI data upload (dari `meta`, hasil GET
    /api/upload/{session_id}/waveform), supaya window Trim SELALU
    berada di dalam rentang data yang benar-benar ada.

    Root cause sebelumnya: window Trim hardcoded ("2024-01-01...")
    tidak overlap dengan waktu asli file AAFM -> ObsPy
    Stream.trim() membuang trace-nya sepenuhnya (Stream jadi
    kosong) -> processing_service.py meng-akses traces[0] pada
    Stream kosong -> HTTP 500 "list index out of range".
    """
    start = _parse_iso(meta["start_time"])
    end = _parse_iso(meta["end_time"])
    mid = start + (end - start) / 2

    resolved = []
    for op in operations:
        op = dict(op)
        if op.get("type") == "trim":
            if op.get("start_time") == "__DATA_START__":
                op["start_time"] = start.isoformat()
            if op.get("end_time") == "__DATA_MID__":
                op["end_time"] = mid.isoformat()
        resolved.append(op)
    return resolved


def run_process_local(base_url, cfg, operations, sampler):
    session_id, meta = upload_local(base_url, cfg)
    try:
        payload = {
            "network": meta["network"],
            "station": meta["station"],
            "location": meta["location"],
            "channel": meta["channel"],
            "start_time": meta["start_time"],
            "end_time": meta["end_time"],
            "operations": resolve_trim_placeholders(operations, meta),
            "session_id": session_id,
        }
        status, resp = http_json("POST", f"{base_url}/process", payload)
        if status != 200:
            raise RuntimeError(f"POST /process failed: HTTP {status} {resp}")
    finally:
        http_json("DELETE", f"{base_url}/api/upload/{session_id}")


SCENARIO_RUNNERS = {
    "fdsn_load_multi": lambda base_url, cfg, scn, sampler: run_fdsn_load_multi(
        base_url, cfg, sampler
    ),
    "local_upload": lambda base_url, cfg, scn, sampler: run_local_upload_only(
        base_url, cfg, sampler
    ),
    "process_local": lambda base_url, cfg, scn, sampler: run_process_local(
        base_url, cfg, scn["operations"], sampler
    ),
}


# --------------------------------------------------------------------------
# Advanced analysis: Spectrogram / PSD / HVSR
# (endpoint & payload dicek langsung dari app/routers/spectrogram.py,
#  app/routers/psd.py, app/routers/hvsr.py — lihat catatan di masing2 fungsi)
# --------------------------------------------------------------------------

def run_spectrogram_local(base_url, cfg, sampler):
    """GET /api/spectrogram?session_id=...&channel=... — sesuai
    app/routers/spectrogram.py (Local: wajib session_id + channel,
    trim opsional, TANPA cache TTL check di sini — di-cache lewat
    spectrogram_cache tapi key-nya termasuk session_id, jadi setiap
    upload baru = selalu miss, konsisten dengan skenario lain di
    benchmark ini yang selalu upload fresh)."""
    channel = cfg["advanced"]["spectrogram_channel"]
    session_id, meta = upload_local(base_url, cfg)
    try:
        params = {"session_id": session_id, "channel": channel}
        status, resp = http_json("GET", f"{base_url}/api/spectrogram?{_qs(params)}")
        if status != 200:
            raise RuntimeError(f"GET /api/spectrogram failed: HTTP {status} {resp}")
    finally:
        http_json("DELETE", f"{base_url}/api/upload/{session_id}")


def run_hvsr_local(base_url, cfg, sampler):
    """GET /api/hvsr?session_id=...&channel_n=...&channel_e=...&channel_z=...
    sesuai app/routers/hvsr.py. Nama channel N/E/Z HARUS sesuai nama
    komponen di file lokal Anda — isi di cfg['advanced'], jangan
    ditebak dari nama channel FDSN (bisa beda konvensi)."""
    adv = cfg["advanced"]
    session_id, meta = upload_local(base_url, cfg)
    try:
        params = {
            "session_id": session_id,
            "channel_n": adv["hvsr_channel_n"],
            "channel_e": adv["hvsr_channel_e"],
            "channel_z": adv["hvsr_channel_z"],
        }
        status, resp = http_json("GET", f"{base_url}/api/hvsr?{_qs(params)}")
        if status != 200:
            raise RuntimeError(f"GET /api/hvsr failed: HTTP {status} {resp}")
    finally:
        http_json("DELETE", f"{base_url}/api/upload/{session_id}")


def _psd_params(cfg, session_id):
    return {"session_id": session_id, "channel": cfg["advanced"]["psd_channel"]}


def _psd_call(base_url, params):
    status, resp = http_json("GET", f"{base_url}/api/psd?{_qs(params)}")
    if status != 200:
        raise RuntimeError(f"GET /api/psd failed: HTTP {status} {resp}")
    return resp


# --------------------------------------------------------------------------
# PREPARE_FUNCS — pola (measure_fn, cleanup_fn).
#
# `measure_fn` adalah bagian yang BENAR-BENAR diukur RAM/CPU-nya
# (dijalankan SETELAH Sampler mulai & baseline window).
# Langkah SETUP/PRIMING (upload, warm-up call cache) dijalankan di
# sini, SEBELUM Sampler dibuat sama sekali — supaya tidak ikut
# mencemari RAM Before / RAM Average / CPU Average dari operasi yang
# sedang diukur.
#
# Default (13 skenario lama) TIDAK berubah perilakunya: upload +
# proses tetap satu paket terukur, exact seperti sebelumnya — hanya
# dibungkus ulang lewat `default_prepare` supaya satu mekanisme
# dipakai untuk semua skenario (lama & baru).
# --------------------------------------------------------------------------

def default_prepare(base_url, cfg, scn):
    def measure():
        SCENARIO_RUNNERS[scn["kind"]](base_url, cfg, scn, None)

    def cleanup():
        pass

    return measure, cleanup


def prepare_fdsn_cached(base_url, cfg, scn):
    """FDSN 1 stasiun — CACHED: resolve window uncached (live-check,
    mundur tanggal kalau target_date sudah cached), lalu PRIME (untimed
    — idempotent, aman walau window sudah cached duluan oleh scenario
    lain), verifikasi FULLY CACHED, baru measured call (harus HIT).

    Window yang dipakai SAMA PERSIS dengan yang dipakai
    prepare_fdsn_uncached (keduanya resolve ke tanggal live-uncached
    pertama dari target_date) — regardless urutan scenario di
    scenarios.json, karena status selalu dicek live ke backend, bukan
    diasumsikan dari config statis."""
    fdsn = cfg["fdsn"]
    station = fdsn["stations"][0]
    channels = fdsn["channels"]

    res = resolve_uncached_window(base_url, cfg, station, channels)
    print(f"[INFO] fdsn_1station_cached: station={station} "
          f"channels={channels} date={res['date']} status=akan di-PRIME "
          f"lalu diukur sebagai CACHED"
          + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))

    prime_window(base_url, cfg, station, channels, res["start"], res["end"])
    verify_fully_cached(base_url, cfg, station, channels, res["start"], res["end"],
                         "fdsn_1station_cached (pre-measure)")

    def measure():
        _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                        channels=channels)

    return measure, (lambda: None)


def prepare_fdsn_uncached(base_url, cfg, scn):
    """FDSN 1 stasiun — UNCACHED: resolve window yang BENAR-BENAR
    belum cached (live-check per channel, mundur tanggal kalau
    target_date sudah cached), lalu measured call TANPA priming
    (guaranteed miss). Setelah request ini, window otomatis menjadi
    cached — diverifikasi di cleanup_fn (untimed)."""
    fdsn = cfg["fdsn"]
    station = fdsn["stations"][0]
    channels = fdsn["channels"]

    res = resolve_uncached_window(base_url, cfg, station, channels)
    print(f"[INFO] fdsn_1station_uncached: station={station} "
          f"channels={channels} date={res['date']} status=UNCACHED"
          + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))

    def measure():
        _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                        channels=channels)

    def cleanup():
        verify_fully_cached(base_url, cfg, station, channels, res["start"],
                             res["end"], "fdsn_1station_uncached (post-measure)")

    return measure, cleanup


def prepare_fdsn_multi_cached(base_url, cfg, scn):
    """N stasiun (fdsn.stations, default 5, subset via --stations) —
    semuanya CACHED: resolve + prime + verify per stasiun (window bisa
    beda tanggal antar-stasiun, wajar — masing2 dicek live), lalu
    measured call memanggil semua stasiun x channel sekali lagi
    (harus semuanya HIT)."""
    fdsn = cfg["fdsn"]
    stations = fdsn["stations"]
    channels = fdsn["channels"]

    windows = {}
    for station in stations:
        res = resolve_uncached_window(base_url, cfg, station, channels)
        print(f"[INFO] fdsn_{len(stations)}station_cached: station={station} "
              f"channels={channels} date={res['date']} status=akan di-PRIME "
              f"lalu diukur sebagai CACHED"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        prime_window(base_url, cfg, station, channels, res["start"], res["end"])
        verify_fully_cached(base_url, cfg, station, channels, res["start"],
                             res["end"], f"fdsn_multi_cached/{station} (pre-measure)")
        windows[station] = res

    def measure():
        for station in stations:
            res = windows[station]
            _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                            channels=channels)

    return measure, (lambda: None)


def prepare_fdsn_multi_uncached(base_url, cfg, scn):
    """N stasiun — semuanya UNCACHED: resolve window live-uncached per
    stasiun (independen, bisa beda tanggal antar-stasiun), measured
    call TANPA priming. Verifikasi semua jadi cached di cleanup_fn."""
    fdsn = cfg["fdsn"]
    stations = fdsn["stations"]
    channels = fdsn["channels"]

    windows = {}
    for station in stations:
        res = resolve_uncached_window(base_url, cfg, station, channels)
        print(f"[INFO] fdsn_{len(stations)}station_uncached: station={station} "
              f"channels={channels} date={res['date']} status=UNCACHED"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        windows[station] = res

    def measure():
        for station in stations:
            res = windows[station]
            _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                            channels=channels)

    def cleanup():
        for station in stations:
            res = windows[station]
            verify_fully_cached(base_url, cfg, station, channels, res["start"],
                                 res["end"], f"fdsn_multi_uncached/{station} (post-measure)")

    return measure, cleanup


def prepare_fdsn_multi_mixed(base_url, cfg, scn):
    """Separuh stasiun pertama dari fdsn.stations = CACHED (resolve +
    prime + verify), separuh berikutnya = UNCACHED (resolve saja, TANPA
    priming). SATU measured scenario memanggil KEDUA kelompok secara
    sequential — cached station pakai window cached-nya, uncached
    station pakai window uncached-nya (bisa beda tanggal per stasiun,
    ditentukan otomatis dari hasil resolve, BUKAN dua benchmark
    terpisah). Verifikasi window uncached menjadi cached di
    cleanup_fn (untimed)."""
    fdsn = cfg["fdsn"]
    stations = fdsn["stations"]
    channels = fdsn["channels"]

    if len(stations) < 2:
        raise RuntimeError(
            "fdsn_multi_mixed butuh minimal 2 stasiun (untuk kelompok "
            f"cached + uncached), tapi hanya {len(stations)} dipilih "
            f"({stations}). Jalankan dengan --stations lebih dari satu."
        )

    half = len(stations) // 2
    cached_stations = stations[:half] or stations[:1]
    uncached_stations = stations[half:] if half else stations[1:]

    windows = {}
    for station in cached_stations:
        res = resolve_uncached_window(base_url, cfg, station, channels)
        print(f"[INFO] fdsn_mixed: station={station} role=CACHED "
              f"channels={channels} date={res['date']}"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        prime_window(base_url, cfg, station, channels, res["start"], res["end"])
        verify_fully_cached(base_url, cfg, station, channels, res["start"],
                             res["end"], f"fdsn_mixed/{station} CACHED (pre-measure)")
        windows[station] = res

    for station in uncached_stations:
        res = resolve_uncached_window(base_url, cfg, station, channels)
        print(f"[INFO] fdsn_mixed: station={station} role=UNCACHED "
              f"channels={channels} date={res['date']}"
              + (f" (alasan: {res['reason']})" if res["cached_before"] else ""))
        windows[station] = res

    def measure():
        # Sequential: kelompok cached dulu, lalu kelompok uncached —
        # sesuai statusnya masing-masing, dalam SATU measured scenario.
        for station in cached_stations:
            res = windows[station]
            _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                            channels=channels)
        for station in uncached_stations:
            res = windows[station]
            _fdsn_call_all(base_url, cfg, [station], res["start"], res["end"],
                            channels=channels)

    def cleanup():
        for station in uncached_stations:
            res = windows[station]
            verify_fully_cached(base_url, cfg, station, channels, res["start"],
                                 res["end"], f"fdsn_mixed/{station} (post-measure)")

    return measure, cleanup


def prepare_spectrogram_local(base_url, cfg, scn):
    def measure():
        run_spectrogram_local(base_url, cfg, None)

    return measure, (lambda: None)


def prepare_hvsr_local(base_url, cfg, scn):
    def measure():
        run_hvsr_local(base_url, cfg, None)

    return measure, (lambda: None)


def prepare_psd_cache_cold(base_url, cfg, scn):
    """PSD COLD: upload FRESH (session_id baru selalu unik) lalu SATU
    kali GET /api/psd. Cache key psd_cache menyertakan session_id
    (lihat app/routers/psd.py: make_cache_key(... session_id ...)),
    jadi upload fresh = otomatis miss, tanpa perlu trik tambahan."""
    def measure():
        session_id, meta = upload_local(base_url, cfg)
        try:
            _psd_call(base_url, _psd_params(cfg, session_id))
        finally:
            http_json("DELETE", f"{base_url}/api/upload/{session_id}")

    return measure, (lambda: None)


def prepare_psd_cache_warm(base_url, cfg, scn):
    """PSD WARM: upload SEKALI, lalu panggil GET /api/psd DUA KALI
    dengan session_id & param yang SAMA persis (supaya cache_key sama
    persis). Panggilan PERTAMA (priming, mengisi psd_cache) dijalankan
    SEBELUM Sampler mulai — TIDAK ikut terukur. Panggilan KEDUA
    (measured) dijamin CACHE HIT karena session_id sama."""
    session_id, meta = upload_local(base_url, cfg)  # setup, untimed
    params = _psd_params(cfg, session_id)
    _psd_call(base_url, params)  # priming call, untimed -> mengisi cache

    def measure():
        _psd_call(base_url, params)  # measured call -> harus CACHE HIT

    def cleanup():
        http_json("DELETE", f"{base_url}/api/upload/{session_id}")

    return measure, cleanup


PREPARE_FUNCS = {
    "fdsn_cached": prepare_fdsn_cached,
    "fdsn_uncached": prepare_fdsn_uncached,
    "fdsn_multi_cached": prepare_fdsn_multi_cached,
    "fdsn_multi_uncached": prepare_fdsn_multi_uncached,
    "fdsn_multi_mixed": prepare_fdsn_multi_mixed,
    "spectrogram_local": prepare_spectrogram_local,
    "hvsr_local": prepare_hvsr_local,
    "psd_cache_cold": prepare_psd_cache_cold,
    "psd_cache_warm": prepare_psd_cache_warm,
}


def prepare_scenario(base_url, cfg, scn):
    """Dispatch ke PREPARE_FUNCS (skenario baru) atau default_prepare
    (13 skenario lama, kind-nya tetap fdsn_load_multi/local_upload/
    process_local — perilaku TIDAK berubah)."""
    fn = PREPARE_FUNCS.get(scn["kind"], default_prepare)
    return fn(base_url, cfg, scn)


# --------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------

def run_scenario(base_url, cfg, scn, server, restart_between):
    if restart_between:
        pid = server.restart()
    else:
        pid = server.attach_pid or server._proc.pid

    # Setup/priming (kalau ada) dijalankan DI LUAR window Sampler —
    # supaya tidak mencemari RAM Before / RAM Average / CPU Average
    # dari operasi yang benar-benar sedang diukur.
    status = "OK"
    measure_fn = None
    cleanup_fn = lambda: None
    try:
        measure_fn, cleanup_fn = prepare_scenario(base_url, cfg, scn)
    except Exception as exc:  # noqa: BLE001
        status = f"FAILED (prepare): {exc}"

    sampler = Sampler(pid)
    sampler.start()

    # Baseline window SEBELUM request ditembak.
    time.sleep(BASELINE_WINDOW_SEC)
    t_before_start = time.time() - BASELINE_WINDOW_SEC
    t_before_end = time.time()
    before_samples = sampler.samples_between(t_before_start, t_before_end)
    ram_before = mean([s[1] for s in before_samples])

    t_req_start = time.time()
    if measure_fn is not None:
        try:
            measure_fn()
        except Exception as exc:  # noqa: BLE001 - benchmark harus tetap lanjut
            status = f"FAILED: {exc}"
    t_req_end = time.time()

    try:
        cleanup_fn()
    except Exception as exc:  # noqa: BLE001
        # Cleanup biasa (mis. DELETE session lokal) boleh gagal tanpa
        # menggagalkan run. TAPI kalau ini verifikasi cache
        # (verify_fully_cached), kegagalannya WAJIB terlihat di status
        # — bukan ditelan diam-diam — karena itu berarti klaim
        # cached/uncached scenario ini tidak valid.
        if status == "OK":
            status = f"FAILED (post-verify): {exc}"

    # Window stabilisasi SETELAH response selesai.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--spawn", help='Perintah start server, mis. "uvicorn app.main:app --port 8000"')
    parser.add_argument("--attach-pid", type=int, help="PID server yang sudah berjalan (mode attach)")
    parser.add_argument("--no-restart", action="store_true", help="Jangan restart server antar-skenario")
    parser.add_argument("--cwd", default=str(BENCH_DIR.parent), help="Working dir untuk --spawn")
    parser.add_argument("--out-prefix", default=None, help="Prefix nama file output (default: timestamp)")
    parser.add_argument(
        "--stations", nargs="+", default=None,
        help=(
            "Subset stasiun FDSN, mis. --stations AAFM atau "
            "--stations AAFM AAI ABJI. Default: fdsn.stations di "
            "scenarios.json (5 stasiun)."
        ),
    )
    parser.add_argument(
        "--date", default=None,
        help=(
            "Override fdsn.target_date (format YYYY-MM-DD). Resolver "
            "tetap mundur otomatis kalau tanggal ini sudah cached."
        ),
    )
    args = parser.parse_args()

    if not args.spawn and not args.attach_pid:
        parser.error("Wajib salah satu: --spawn '<cmd>' atau --attach-pid <pid>")

    cfg = json.loads(SCENARIOS_PATH.read_text())
    if args.stations:
        cfg["fdsn"]["stations"] = args.stations
    # target_date SELALU kemarin (lokal) secara default — TIDAK PERNAH
    # hari ini, TIDAK di-hardcode. scenarios.json tidak lagi menyimpan
    # tanggal tetap; nilai apa pun di sana diabaikan kecuali --date
    # diberikan secara eksplisit.
    cfg["fdsn"]["target_date"] = args.date or default_target_date()
    print(f"[CONFIG] FDSN stations={cfg['fdsn']['stations']} "
          f"channels={cfg['fdsn']['channels']} "
          f"target_date={cfg['fdsn']['target_date']} "
          f"({'override --date' if args.date else 'otomatis: kemarin, lokal'})\n")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = args.out_prefix or time.strftime("%Y%m%d_%H%M%S")

    server = ServerHandle(spawn_cmd=args.spawn, attach_pid=args.attach_pid, cwd=args.cwd)
    if not args.attach_pid:
        server.start()

    restart_between = not args.no_restart and not args.attach_pid

    all_results = []
    all_raw = {}

    try:
        for scn in cfg["scenarios"]:
            print(f"[RUN] {scn['id']} - {scn['label']}")
            result, raw = run_scenario(
                args.base_url, cfg, scn, server, restart_between
            )
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

    csv_path = RESULTS_DIR / f"{run_id}_summary.csv"
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

    raw_path = RESULTS_DIR / f"{run_id}_raw_timeseries.json"
    raw_path.write_text(json.dumps(all_raw, indent=2))

    print(f"\nSummary CSV : {csv_path}")
    print(f"Raw timeseries JSON : {raw_path}")


if __name__ == "__main__":
    main()