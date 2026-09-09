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

Konsep benchmark: DATA 1 HARI (24 jam) PENUH — data partial TIDAK
PERNAH dipakai sebagai hasil benchmark — dua peran window per stasiun:

  1. CACHED  -> fdsn.target_date (default: KEMARIN, lokal, TIDAK
     di-hardcode; override --date) adalah TITIK AWAL pencarian, BUKAN
     tanggal yang wajib dipakai sampai akhir. Alurnya (lihat
     determine_cached_role_date() + resolve_cached_window()):
       a. Kalau target_date SUDAH fully cached (live-check ke
          GET /api/waveform/status) -> langsung dipakai.
       b. Kalau belum cached TAPI has_full_day_fdsn_data() bilang
          datanya lengkap 24 jam untuk semua channel -> di-PRIME
          (download), lalu diverifikasi ulang; kalau benar-benar
          fully cached -> dipakai untuk measured call (harus HIT).
       c. Kalau datanya sendiri TIDAK lengkap 24 jam di FDSN (mis.
          sensor mati sebagian hari) -> tanggal ini TIDAK BOLEH
          dipakai (bukan FAILED — cuma di-skip), mundur satu hari,
          ulangi dari (a) di tanggal baru. Terus sampai ketemu
          tanggal yang datanya benar-benar lengkap.
     Lihat resolve_cached_window().

  2. UNCACHED -> dicari MUNDUR mulai dari target_date - 1 hari (TIDAK
     PERNAH target_date itu sendiri, karena sudah dipakai role CACHED
     di atas). Kandidat tanggal harus lolos DUA syarat:
       a. live-check /api/waveform/status: TIDAK SATU channel pun
          boleh sudah cached (kalau ada -> mundur).
       b. has_full_day_fdsn_data(): SEMUA channel harus punya data
          FDSN 24 jam penuh TANPA GAP (satu fetch 24-jam per channel,
          bypass cache, lalu Stream.get_gaps() + cek cakupan awal/
          akhir GABUNGAN semua trace/segmen) — kalau tidak lengkap,
          SKIP tanggal ini (data tidak lengkap TIDAK BOLEH dipakai
          sebagai benchmark 1 hari), mundur lagi.
     TIDAK ADA priming untuk peran ini — measured call langsung
     (guaranteed miss), lalu verify_fully_cached() sesudahnya (kalau
     masih ada channel yang belum cached, scenario DIANGGAP GAGAL).
     Lihat resolve_uncached_window().

  Contoh (target_date = 8 Sep): 8 Sep dipakai untuk CACHED apa pun
  isinya (prime kalau perlu). Untuk UNCACHED, mulai cek 7 Sep -> kalau
  7 Sep sudah cached, mundur ke 6 Sep; kalau 7 Sep belum cached tapi
  datanya bolong di FDSN, tetap mundur ke 6 Sep; begitu ketemu tanggal
  yang belum cached DAN datanya lengkap 24 jam, tanggal itu dipakai
  (tidak perlu cek lebih mundur lagi).

  Kasus nyata yang melatarbelakangi aturan (b): IA.AAFM 2026-09-08
  cuma punya data FDSN jam 00:00-04:00 (dikonfirmasi
  scripts/diagnose_fdsn_hourly.py --check-fdsn -> FDSNNoDataException
  untuk sisa hari) — window begini TIDAK AKAN PERNAH fully cached
  berapa kali pun di-download, karena backend memang sengaja skip jam
  yang FDSNNoDataException (lihat waveform_provider_service.get_waveform()).

  fdsn.max_lookback_days (scenarios.json, default 30) membatasi berapa
  hari mundur dicoba. --skip-availability-check menonaktifkan syarat
  (b) di atas (TIDAK direkomendasikan).

Optimasi lintas-scenario (PENTING supaya cepat — lihat komentar di
_CACHED_ROLE_MEMO / _UNCACHED_SEARCH_POINTER / _FDSN_AVAILABILITY_CACHE
untuk detail lengkap):
  - has_full_day_fdsn_data() di-memo per (station, channel, date) —
    fetch FDSN LANGSUNG (bukan lewat backend) untuk kombinasi yang
    SAMA hanya terjadi SEKALI per run, siapa pun pemanggilnya.
  - resolve_cached_window() di-memo per station: begitu tanggal CACHED
    ketemu (dan sudah dipastikan fully cached), fdsn_cached,
    fdsn_multi_cached, dan grup CACHED di fdsn_multi_mixed untuk
    station yang sama TIDAK melakukan request/pencarian apa pun lagi —
    langsung pakai hasil yang sudah ada.
  - resolve_uncached_window() melanjutkan pencarian dari pointer per
    station (tanggal SATU HARI di bawah tanggal UNCACHED terakhir yang
    ditemukan untuk station itu), BUKAN mulai lagi dari
    cached_date - 1. Ini valid karena semua tanggal DI ATAS pointer
    sudah TERBUKTI reject (sudah cached, atau data FDSN-nya tidak
    lengkap) — status itu TIDAK PERNAH berbalik dalam satu run
    benchmark (backend cache cuma bertambah, dan data historis di
    FDSN tidak tiba-tiba jadi lengkap) — jadi aman dilewati permanen,
    TANPA mengurangi validitas hasil (definisi CACHED/UNCACHED/MIXED
    di atas TIDAK berubah sedikit pun, cuma pencarian yang tidak perlu
    diulang dihindari).
  - Verifikasi ganda yang sebelumnya ada (resolve_cached_window()
    sudah menjamin fully-cached, tapi prepare_fdsn_cached()/
    prepare_fdsn_mixed() masih memanggil verify_fully_cached() SEKALI
    LAGI persis sesudahnya) dihapus — post-condition itu sudah
    dijamin oleh resolver sendiri.

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

  # Nonaktifkan validasi ketersediaan FDSN penuh 24 jam (TIDAK
  # direkomendasikan, hanya untuk debugging cepat):
  python benchmark/fdsn_cache_benchmark.py --attach-pid 10956 \
      --stations AAFM --skip-availability-check
"""

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import psutil

# Supaya bisa import modul app.* langsung (untuk has_full_day_fdsn_data,
# yang butuh app.core.fdsn_client & app.core.config — bypass cache,
# read-only, TIDAK menulis apa pun ke DB/disk aplikasi). Script ini
# tetap dijalankan dari root project seperti biasa.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BENCH_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = BENCH_DIR / "scenarios.json"
RESULTS_DIR = BENCH_DIR / "results"

SAMPLE_INTERVAL_SEC = 0.2
BASELINE_WINDOW_SEC = 1.5
STABLE_WAIT_SEC = 2.0
STABLE_WINDOW_SEC = 1.5

MIN_STATIONS = 1
MAX_STATIONS = 5

# Toleransi pembacaan sampel di tepi hari (detik) — trace real dari
# BMKG jarang mulai/berakhir TEPAT di 00:00:00.000000, ada slack
# beberapa milidetik/detik wajar karena sample rate. Longgar tapi
# tetap ketat: kalau lebih dari ini, dianggap coverage TIDAK penuh.
COVERAGE_EDGE_TOLERANCE_SEC = 2.0


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


_FDSN_AVAILABILITY_CACHE = {}  # {(station, channel, date_str): (bool, str)} — memo dalam satu run

# --------------------------------------------------------------------------
# Memoization LINTAS SCENARIO dalam satu run (bukan cuma per-panggilan) —
# ini yang membuat fdsn_multi_cached/fdsn_multi_uncached/fdsn_multi_mixed
# TIDAK mengulang pencarian tanggal yang sudah ditemukan scenario
# sebelumnya untuk station yang sama.
#
# _CACHED_ROLE_MEMO[station] = hasil LENGKAP resolve_cached_window()
#   (tanggal sudah dipastikan fully cached — via already-cached ATAU
#   sudah di-download+diverifikasi). SEKALI diisi, aman dipakai ulang
#   TANPA request apa pun ke backend/FDSN lagi, karena cache di backend
#   TIDAK PERNAH "mundur" jadi uncached lagi dalam satu run benchmark
#   ini — jadi tidak ada risiko stale.
#
# _UNCACHED_SEARCH_POINTER[station] = tanggal (datetime) TERJAUH yang
#   sudah pernah diperiksa untuk peran UNCACHED station ini. Panggilan
#   berikutnya untuk station yang sama (mis. fdsn_uncached lalu
#   fdsn_multi_uncached memakai station yang sama) mulai mundur dari
#   pointer ini, BUKAN dari cached_role_date - 1 lagi — karena semua
#   tanggal di ATAS pointer sudah TERBUKTI reject (sudah cached, atau
#   FDSN tidak lengkap) dan status itu TIDAK PERNAH berbalik dalam satu
#   run (cached tetap cached, FDSN yang tidak lengkap tidak akan
#   mendadak lengkap). Aman untuk dilewati permanen.
_CACHED_ROLE_MEMO = {}  # {station: resolve_cached_window() result dict}
_UNCACHED_SEARCH_POINTER = {}  # {station: datetime — tanggal berikutnya yang belum diperiksa}


class _FDSNAvailabilityConnectivityError(Exception):
    """Discovery/koneksi/timeout gagal setelah retry — BUKAN bukti
    data tidak lengkap. Resolver TIDAK boleh menafsirkan ini sebagai
    'data tidak ada' dan pindah tanggal — harus berhenti/lapor jelas."""


def _fresh_fdsn_client():
    """Client FDSN baru, konfigurasi PERSIS yang dipakai backend
    (app/core/fdsn_client.py) — dibuat ulang tiap percobaan supaya
    discovery dicoba lagi dari nol kalau attempt sebelumnya gagal."""
    from obspy.clients.fdsn import Client
    from app.core.config import (
        BMKG_URL, BMKG_USERNAME, BMKG_PASSWORD, FDSN_TIMEOUT_SECONDS,
    )
    return Client(
        BMKG_URL, user=BMKG_USERNAME, password=BMKG_PASSWORD,
        timeout=FDSN_TIMEOUT_SECONDS,
    )


def _get_full_day_stream_with_retry(network, station, location, channel,
                                     day_start, day_end):
    """Ambil SATU hari penuh (24 jam) LANGSUNG dari FDSN, bypass cache/
    backend sepenuhnya — read-only, TIDAK menulis apa pun. Dibungkus
    retry ala backend (fresh Client tiap percobaan, MAX_DOWNLOAD_ATTEMPTS
    / RETRY_DELAY_SECONDS dari app.core.config) untuk error transient
    (koneksi/timeout/discovery). FDSNNoDataException TIDAK di-retry —
    itu definitif 'tidak ada data sama sekali', bukan soal konektivitas.
    """
    import socket
    import time as _time
    import urllib.error as _urllib_error
    from obspy.clients.fdsn.header import FDSNNoDataException
    from app.core.config import MAX_DOWNLOAD_ATTEMPTS, RETRY_DELAY_SECONDS

    try:
        import requests
        _requests_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ProxyError,
            requests.exceptions.SSLError,
        )
    except ImportError:
        _requests_errors = ()

    last_exc = None
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            client = _fresh_fdsn_client()
            return client.get_waveforms(
                network=network, station=station, location=location,
                channel=channel, starttime=day_start, endtime=day_end,
            )
        except FDSNNoDataException:
            return None  # definitif: tidak ada data sama sekali
        except (
            TimeoutError, socket.timeout, ConnectionError,
            _urllib_error.URLError, *_requests_errors,
        ) as exc:
            last_exc = exc
        except Exception as exc:  # noqa: BLE001 - termasuk error discovery FDSN umum
            last_exc = exc

        if attempt < MAX_DOWNLOAD_ATTEMPTS:
            _time.sleep(RETRY_DELAY_SECONDS)

    raise _FDSNAvailabilityConnectivityError(
        f"{type(last_exc).__name__}: {last_exc} "
        f"(gagal setelah {MAX_DOWNLOAD_ATTEMPTS} percobaan)"
    )


def has_full_day_fdsn_data(network, station, location, channel, date_str):
    """
    True kalau (network, station, location, channel) BENAR-BENAR
    punya data FDSN untuk SELURUH 24 jam `date_str` (00:00:00 ->
    besoknya 00:00:00), TANPA GAP — dicek LANGSUNG ke FDSN, bypass
    cache/backend, read-only.

    Metodologi (satu fetch 24-jam per channel, BUKAN 24 fetch per
    jam — jauh lebih murah, tapi tetap benar untuk multi-trace/gap):
      1. Ambil seluruh stream 24 jam sekaligus.
      2. Kalau kosong / FDSNNoDataException -> jelas tidak lengkap.
      3. `Stream.get_gaps()` pada stream yang SUDAH di-merge(method=1)
         -> daftar gap ANTAR SEGMEN/TRACE (termasuk kalau datanya
         datang sebagai banyak trace terpisah, mis. akibat instrument
         restart/parameter berubah di tengah hari). Ada gap dengan
         durasi > toleransi -> TIDAK lengkap.
      4. Cakupan ujung: waktu mulai trace PALING AWAL harus <=
         day_start + toleransi, dan waktu selesai trace PALING AKHIR
         harus >= day_end - toleransi (menutup KESELURUHAN 00:00-24:00,
         bukan cuma sebagian). Ini menutup kasus AAFM 2026-09-08 (data
         cuma sampai jam 04:00 -> trace terakhir berakhir jauh sebelum
         day_end -> gagal di sini).

    Return (is_full: bool, detail: str). Exception
    `_FDSNAvailabilityConnectivityError` MENJALAR ke pemanggil (bukan
    ditangkap jadi False) — error konektivitas TIDAK BOLEH ditafsirkan
    sebagai "data tidak lengkap".
    """
    from obspy import Stream, UTCDateTime

    cache_key = (station, channel, date_str)
    if cache_key in _FDSN_AVAILABILITY_CACHE:
        return _FDSN_AVAILABILITY_CACHE[cache_key]

    day_start = UTCDateTime(date_str + "T00:00:00")
    day_end = day_start + 24 * 3600

    stream = _get_full_day_stream_with_retry(
        network, station, location, channel, day_start, day_end
    )

    if stream is None or len(stream) == 0:
        result = (False, "FDSN tidak mengembalikan data sama sekali untuk hari ini")
        _FDSN_AVAILABILITY_CACHE[cache_key] = result
        return result

    # Gabungkan (merge) dulu supaya get_gaps() menilai SELURUH
    # segmen/trace sebagai satu deret waktu, bukan trace lepas-lepas.
    merged = Stream(stream.copy()).merge(method=1)

    gaps = merged.get_gaps()
    # get_gaps() juga melaporkan overlap sebagai delta negatif —
    # yang jadi perhatian kita HANYA gap (delta waktu > toleransi),
    # overlap tidak berarti data hilang.
    real_gaps = [g for g in gaps if g[6] > COVERAGE_EDGE_TOLERANCE_SEC]
    if real_gaps:
        gap_desc = "; ".join(
            f"{g[4]} -> {g[5]} ({g[6]:.1f}s)" for g in real_gaps[:5]
        )
        more = f" (+{len(real_gaps) - 5} gap lain)" if len(real_gaps) > 5 else ""
        result = (False, f"Ditemukan {len(real_gaps)} gap: {gap_desc}{more}")
        _FDSN_AVAILABILITY_CACHE[cache_key] = result
        return result

    # Cakupan ujung: gabungan SEMUA trace (bukan cuma trace pertama)
    # harus menutup 00:00:00 -> 24:00:00 penuh.
    earliest_start = min(tr.stats.starttime for tr in merged)
    latest_end = max(tr.stats.endtime for tr in merged)

    if earliest_start > day_start + COVERAGE_EDGE_TOLERANCE_SEC:
        result = (False, (
            f"Data baru mulai {earliest_start} — tidak menutup awal "
            f"hari ({day_start})"
        ))
        _FDSN_AVAILABILITY_CACHE[cache_key] = result
        return result

    if latest_end < day_end - COVERAGE_EDGE_TOLERANCE_SEC:
        result = (False, (
            f"Data berhenti di {latest_end} — tidak menutup akhir hari "
            f"({day_end}), kemungkinan ada data hilang di sisa hari"
        ))
        _FDSN_AVAILABILITY_CACHE[cache_key] = result
        return result

    result = (True, (
        f"Cakupan penuh {earliest_start} -> {latest_end} "
        f"({len(merged)} trace setelah merge, 0 gap > {COVERAGE_EDGE_TOLERANCE_SEC}s)"
    ))
    _FDSN_AVAILABILITY_CACHE[cache_key] = result
    return result


def determine_cached_role_date(base_url, fdsn_cfg, station, channels):
    """
    Tentukan tanggal yang akan dipakai untuk peran CACHED, murni
    READ-ONLY (live cache-status check + has_full_day_fdsn_data),
    TANPA mendownload apa pun — dipakai oleh resolve_cached_window()
    (untuk tahu tanggal mana yang akan di-prime) dan
    resolve_uncached_window() (untuk tahu batas mundur, TANPA perlu
    ikut men-download apa pun dari sini).

    Mulai dari fdsn_cfg["target_date"], mundur satu hari setiap kali
    tanggal kandidat TIDAK memenuhi syarat CACHED:
      - kandidat LOLOS kalau SUDAH fully cached (tinggal dipakai), ATAU
      - kandidat LOLOS kalau BELUM cached tapi has_full_day_fdsn_data()
        TRUE di semua channel (artinya download akan berhasil membuat
        window ini fully cached).
      - kandidat GAGAL (mundur) kalau belum cached DAN datanya sendiri
        tidak lengkap 24 jam di FDSN — data tidak lengkap TIDAK BOLEH
        jadi hasil benchmark.

    Return dict: {"date", "start", "end", "already_cached", "reason"}
    """
    max_lookback = fdsn_cfg.get("max_lookback_days", 30)
    date = datetime.fromisoformat(fdsn_cfg["target_date"])

    for _ in range(max_lookback):
        date_str = date.strftime("%Y-%m-%d")
        start, end = _day_range(date_str)

        status_map = {
            ch: check_waveform_cached(base_url, fdsn_cfg, station, ch, start, end)
            for ch in channels
        }
        if all(status_map.values()):
            return {
                "date": date_str, "start": start, "end": end,
                "already_cached": True,
                "reason": f"{date_str} sudah fully cached",
            }

        availability = {
            ch: has_full_day_fdsn_data(
                fdsn_cfg["network"], station, fdsn_cfg["location"], ch, date_str
            )
            for ch in channels
        }
        incomplete = {
            ch: detail for ch, (is_full, detail) in availability.items()
            if not is_full
        }
        if not incomplete:
            return {
                "date": date_str, "start": start, "end": end,
                "already_cached": False,
                "reason": (
                    f"{date_str} belum cached, tapi data FDSN lengkap "
                    "24 jam untuk semua channel — akan di-download"
                ),
            }

        detail_str = "; ".join(f"{ch}: {d}" for ch, d in incomplete.items())
        print(f"      [SKIP] {station} @ {date_str}: data FDSN tidak "
              f"lengkap 24 jam untuk channel {list(incomplete)} "
              f"({detail_str}) — mundur ke tanggal sebelumnya")
        date -= timedelta(days=1)

    raise RuntimeError(
        f"Tidak menemukan tanggal yang datanya lengkap 24 jam untuk "
        f"peran CACHED — station={station} channels={channels} dalam "
        f"{max_lookback} hari mundur dari {fdsn_cfg['target_date']}. "
        "Semua tanggal yang dicoba datanya tidak lengkap di FDSN — "
        "perluas fdsn.max_lookback_days di scenarios.json, atau cek "
        "scripts/diagnose_fdsn_hourly.py --check-fdsn untuk detail "
        "per-jam."
    )


def resolve_cached_window(base_url, fdsn_cfg, station, channels):
    """
    Window untuk test CACHED. target_date HANYALAH TITIK AWAL
    pencarian, BUKAN tanggal yang wajib dipakai sampai akhir:
      1. Tentukan tanggal kandidat via determine_cached_role_date()
         (read-only — sudah menjamin tanggal ini SUDAH cached, atau
         datanya lengkap 24 jam sehingga download DIPREDIKSI berhasil).
      2. Kalau kandidat belum cached -> PRIME (download) di sini.
      3. Verifikasi ulang fully cached SETELAH download:
         - berhasil -> tanggal ini dipakai untuk measured CACHED.
         - MASIH gagal padahal has_full_day_fdsn_data() bilang datanya
           lengkap -> ini BUKAN soal tanggal (availability sudah
           dikonfirmasi lengkap), jadi TIDAK mundur — di-raise sebagai
           kegagalan nyata (kemungkinan bug download/save di backend,
           lihat scripts/diagnose_fdsn_hourly.py), supaya tidak
           tertutupi dengan pindah tanggal diam-diam.

    Return dict: {"date", "start", "end", "reason", "needed_priming"}

    MEMOIZED per station (_CACHED_ROLE_MEMO): panggilan kedua+ untuk
    station yang SAMA dalam satu run (mis. fdsn_cached lalu
    fdsn_multi_cached lalu grup cached di fdsn_multi_mixed) langsung
    return hasil yang sudah diverifikasi TANPA request apa pun lagi —
    aman karena begitu tanggal ini fully cached, ia TIDAK PERNAH
    "mundur" jadi uncached lagi dalam satu run.
    """
    if station in _CACHED_ROLE_MEMO:
        return _CACHED_ROLE_MEMO[station]

    candidate = determine_cached_role_date(base_url, fdsn_cfg, station, channels)
    date_str, start, end = candidate["date"], candidate["start"], candidate["end"]

    if candidate["already_cached"]:
        result = {
            "date": date_str, "start": start, "end": end,
            "reason": candidate["reason"], "needed_priming": False,
        }
        _CACHED_ROLE_MEMO[station] = result
        return result

    print(f"      [DOWNLOAD] {station} @ {date_str}: {candidate['reason']}")
    prime_window(base_url, fdsn_cfg, station, channels, start, end)

    status_map = {
        ch: check_waveform_cached(base_url, fdsn_cfg, station, ch, start, end)
        for ch in channels
    }
    still_missing = [ch for ch, ok in status_map.items() if not ok]
    if still_missing:
        raise RuntimeError(
            f"CACHED gagal: station={station} @ {date_str} channel "
            f"{still_missing} MASIH download_needed=True SETELAH "
            "download, padahal has_full_day_fdsn_data() sebelumnya "
            "memastikan data FDSN lengkap 24 jam untuk tanggal ini. "
            "Ini indikasi masalah nyata di alur download/save backend "
            "(BUKAN soal pemilihan tanggal) — cek log backend dan "
            "scripts/diagnose_fdsn_hourly.py --station "
            f"{station} --date {date_str} --check-fdsn sebelum "
            "melanjutkan benchmark."
        )

    result = {
        "date": date_str, "start": start, "end": end,
        "reason": f"{date_str} berhasil di-download dan fully cached",
        "needed_priming": True,
    }
    _CACHED_ROLE_MEMO[station] = result
    return result


def resolve_uncached_window(base_url, fdsn_cfg, station, channels):
    """
    Window untuk test UNCACHED: dicari MUNDUR mulai dari SATU HARI
    SEBELUM tanggal yang dipakai peran CACHED (ditentukan via
    determine_cached_role_date() — read-only, TIDAK mendownload apa
    pun dari sini, jadi TIDAK peduli apakah scenario CACHED sudah
    benar-benar dijalankan lebih dulu atau belum: hasilnya konsisten
    karena selalu dicek live). Untuk tiap kandidat tanggal, DUA syarat
    harus lolos SEBELUM diterima:
      a. live-check /api/waveform/status: TIDAK SATU channel pun
         boleh sudah cached (kalau ada yang cached -> SKIP, mundur).
      b. has_full_day_fdsn_data(): SEMUA channel harus punya data FDSN
         24 jam penuh tanpa gap (kalau tidak lengkap -> SKIP, mundur —
         data tidak lengkap TIDAK BOLEH dipakai sebagai benchmark
         1 hari).
    TIDAK ADA priming di sini — caller memanggil measured request
    langsung (guaranteed miss), lalu verify_fully_cached() sesudahnya.

    Return dict: {"date", "start", "end", "reason"}

    DIOPTIMASI dengan dua memo lintas-scenario (lihat komentar di
    _CACHED_ROLE_MEMO / _UNCACHED_SEARCH_POINTER):
      1. Batas atas pencarian (tanggal peran CACHED - 1) diambil dari
         _CACHED_ROLE_MEMO kalau sudah pernah di-resolve (TANPA
         memanggil determine_cached_role_date() lagi — fungsi itu
         sendiri melakukan loop mundur + availability check yang bisa
         mahal). Fallback ke determine_cached_role_date() (read-only)
         hanya kalau station ini belum pernah lewat resolve_cached_window().
      2. Titik mulai scan MUNDUR dilanjutkan dari
         _UNCACHED_SEARCH_POINTER[station] kalau ada (posisi persis
         setelah tanggal terakhir yang DITEMUKAN untuk station ini) —
         BUKAN mulai dari cached_role_date - 1 lagi. Semua tanggal di
         ATAS pointer itu SUDAH TERBUKTI reject (sudah cached / FDSN
         tidak lengkap), status itu tidak pernah berbalik dalam satu
         run, jadi aman dilewati tanpa re-check.
    """
    max_lookback = fdsn_cfg.get("max_lookback_days", 30)
    check_availability = fdsn_cfg.get("check_availability", True)

    if station in _CACHED_ROLE_MEMO:
        cached_role_date_str = _CACHED_ROLE_MEMO[station]["date"]
    else:
        cached_role_date_str = determine_cached_role_date(
            base_url, fdsn_cfg, station, channels
        )["date"]

    if station in _UNCACHED_SEARCH_POINTER:
        date = _UNCACHED_SEARCH_POINTER[station]
    else:
        date = datetime.fromisoformat(cached_role_date_str) - timedelta(days=1)

    for _ in range(max_lookback):
        date_str = date.strftime("%Y-%m-%d")
        start, end = _day_range(date_str)

        status_map = {
            ch: check_waveform_cached(base_url, fdsn_cfg, station, ch, start, end)
            for ch in channels
        }
        if any(status_map.values()):
            cached_chs = [ch for ch, is_cached in status_map.items() if is_cached]
            print(f"      [SKIP] {station} @ {date_str}: sudah "
                  f"(sebagian) ter-cache untuk channel {cached_chs} — "
                  "mundur ke tanggal sebelumnya")
            date -= timedelta(days=1)
            continue

        if check_availability:
            availability = {
                ch: has_full_day_fdsn_data(
                    fdsn_cfg["network"], station, fdsn_cfg["location"], ch, date_str
                )
                for ch in channels
            }
            incomplete = {
                ch: detail for ch, (is_full, detail) in availability.items()
                if not is_full
            }
            if incomplete:
                detail_str = "; ".join(f"{ch}: {d}" for ch, d in incomplete.items())
                print(f"      [SKIP] {station} @ {date_str}: belum "
                      f"cached, TAPI data FDSN tidak lengkap 24 jam "
                      f"untuk channel {list(incomplete)} ({detail_str}) "
                      "— mundur ke tanggal sebelumnya")
                date -= timedelta(days=1)
                continue

        # Simpan pointer SATU hari di bawah tanggal yang ditemukan —
        # panggilan berikutnya untuk station ini (scenario lain yang
        # juga butuh peran UNCACHED) langsung lanjut dari sini, tidak
        # perlu scan ulang dari cached_role_date - 1.
        _UNCACHED_SEARCH_POINTER[station] = date - timedelta(days=1)

        return {
            "date": date_str, "start": start, "end": end,
            "reason": (
                f"{date_str} belum cached DAN data FDSN lengkap 24 jam "
                "untuk semua channel"
            ),
        }

    raise RuntimeError(
        f"Tidak menemukan window UNCACHED yang juga lengkap 24 jam "
        f"untuk station={station} channels={channels} dalam "
        f"{max_lookback} hari mundur dari tanggal CACHED "
        f"({cached_role_date_str}). Semua tanggal yang dicoba sudah "
        "(sebagian) ter-cache ATAU datanya sendiri tidak lengkap di "
        "FDSN — perluas fdsn.max_lookback_days di scenarios.json kalau "
        "ini memang diharapkan, atau cek "
        "scripts/diagnose_fdsn_hourly.py --check-fdsn untuk detail "
        "per-jam."
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
    """SEMUA stasiun terpilih — CACHED: window ditentukan
    resolve_cached_window() (target_date sebagai TITIK AWAL pencarian,
    mundur otomatis kalau datanya tidak lengkap; download+verifikasi
    SUDAH dilakukan di dalam resolve_cached_window()), lalu measured
    call di sini (harus HIT semua, karena sudah dipastikan fully
    cached oleh resolver).

    Catatan optimasi: TIDAK ADA verify_fully_cached() tambahan di sini
    lagi — resolve_cached_window() SUDAH menjamin postcondition "fully
    cached" sebagai bagian dari kontraknya sendiri sebelum ia return
    (lewat cabang already_cached, ATAU lewat cabang download+verifikasi
    eksplisit yang me-raise kalau gagal). Memanggil verify_fully_cached()
    lagi di sini cuma mengulang N-channel HTTP check yang hasilnya sudah
    pasti True — persis jenis request redundant yang ingin dihilangkan."""
    channels = fdsn_cfg["channels"]
    windows = {}
    for station in stations:
        res = resolve_cached_window(base_url, fdsn_cfg, station, channels)
        print(f"[INFO] {scn_id}: station={station} channels={channels} "
              f"date={res['date']} ({res['reason']})")
        windows[station] = res

    def measure():
        for station in stations:
            res = windows[station]
            _fdsn_call_all(base_url, fdsn_cfg, [station], res["start"], res["end"],
                            channels)

    return measure, (lambda: None)


def prepare_fdsn_uncached(base_url, fdsn_cfg, stations, scn_id):
    """SEMUA stasiun terpilih — UNCACHED: window dicari MUNDUR dari
    target_date - 1 hari (resolve_uncached_window — belum cached DAN
    data FDSN lengkap 24 jam), measured call TANPA priming (guaranteed
    miss). Verifikasi semua jadi cached di cleanup_fn."""
    channels = fdsn_cfg["channels"]
    windows = {}
    for station in stations:
        res = resolve_uncached_window(base_url, fdsn_cfg, station, channels)
        print(f"[INFO] {scn_id}: station={station} channels={channels} "
              f"date={res['date']} status=UNCACHED ({res['reason']})")
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
    """Bagi `stations` jadi kelompok CACHED (resolve_cached_window +
    prime kalau perlu + verify) dan UNCACHED (resolve_uncached_window,
    TANPA priming) via split_mixed_stations() — konsep cache yang SAMA
    persis dengan prepare_fdsn_cached/prepare_fdsn_uncached di atas.
    SATU measured scenario memanggil KEDUA kelompok secara sequential.
    """
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
        # Tidak ada verify_fully_cached() tambahan di sini — lihat
        # catatan optimasi di prepare_fdsn_cached(), alasannya sama
        # persis: resolve_cached_window() sudah menjaminnya.
        res = resolve_cached_window(base_url, fdsn_cfg, station, channels)
        print(f"[INFO] {scn_id}: station={station} role=CACHED "
              f"channels={channels} date={res['date']} ({res['reason']})")
        windows[station] = res

    for station in uncached_stations:
        res = resolve_uncached_window(base_url, fdsn_cfg, station, channels)
        print(f"[INFO] {scn_id}: station={station} role=UNCACHED "
              f"channels={channels} date={res['date']} ({res['reason']})")
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
    parser.add_argument(
        "--skip-availability-check", action="store_true",
        help=(
            "TIDAK DIREKOMENDASIKAN. Lewati has_full_day_fdsn_data() "
            "(validasi data FDSN 24 jam penuh via get_gaps()+coverage) "
            "saat resolve tanggal — resolver kembali hanya mengecek "
            "'belum cached' seperti sebelumnya, berisiko memilih "
            "tanggal yang datanya sendiri bolong di FDSN (window "
            "TIDAK AKAN PERNAH fully cached)."
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
        "check_availability": not args.skip_availability_check,
    }
    fdsn_cfg["target_date"] = args.date or default_target_date()

    print(f"[CONFIG] FDSN stations={stations} (n={len(stations)}) "
          f"channels={fdsn_cfg['channels']} "
          f"target_date={fdsn_cfg['target_date']} "
          f"({'override --date' if args.date else 'otomatis: kemarin, lokal'}) "
          f"availability_check={'ON' if fdsn_cfg['check_availability'] else 'OFF (--skip-availability-check)'}\n")

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