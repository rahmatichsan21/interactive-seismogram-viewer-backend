# `benchmark`

Folder ini berisi benchmark performa (RAM/CPU) backend yang dijalankan
**dari luar** aplikasi — script mengirim request HTTP nyata ke server FastAPI
yang sedang berjalan dan mengukur resource process-nya via `psutil`. Bukan
unit test dan tidak mengubah kode aplikasi; endpoint yang dipanggil adalah
endpoint yang sudah ada di `app/routers/`.

Benchmark ini dipertahankan terpisah dari `scripts/` karena tujuannya
mengukur performa runtime API (waktu, RSS memory, CPU) di berbagai skenario
beban kerja, bukan diagnosa/maintenance data.

## Benchmark yang tersedia

| Script | Tujuan |
| --- | --- |
| `ram_cpu_benchmark.py` | Menjalankan 22 skenario (13 skenario dasar Local Upload/Processing/Trim/Filter/Instrument Correction + 9 skenario lanjutan FDSN cached/uncached/multi/mixed, Spectrogram, PSD cold/warm, HVSR) lewat endpoint backend, mengukur RSS dan CPU proses. |
| `fdsn_cache_benchmark.py` | Retest khusus untuk 5 skenario FDSN (`fdsn_cached`, `fdsn_uncached`, `fdsn_multi_cached`, `fdsn_multi_uncached`, `fdsn_multi_mixed`) via `GET /api/waveform` dan `GET /api/waveform/status`. Terpisah dari `ram_cpu_benchmark.py` (script itu tidak diubah/dijalankan ulang oleh script ini) dan tidak menjalankan skenario Local Upload/Processing/Spectrogram/PSD/HVSR. |

Endpoint yang dipanggil kedua benchmark (semua sudah ada di
`app/routers/`, tidak ada endpoint baru yang dibuat untuk benchmark):
`GET /api/waveform`, `GET /api/waveform/status`, `POST /api/upload/miniseed`,
`POST /api/upload/stationxml`, `GET /api/upload/{session_id}/waveform`,
`DELETE /api/upload/{session_id}`, `POST /process`, `GET /api/spectrogram`,
`GET /api/psd`, `GET /api/hvsr`.

## Cara menjalankan

Kedua script mendukung dua mode server: **spawn** (script yang menjalankan
uvicorn) atau **attach** (menempel ke server dev yang sudah berjalan). Salah
satu dari `--spawn` atau `--attach-pid` wajib diisi. Dijalankan dari root
backend dengan virtualenv aktif.

```powershell
# Mode A - script menjalankan server sendiri
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --spawn "uvicorn app.main:app --host 127.0.0.1 --port 8000" `
    --base-url http://127.0.0.1:8000

# Mode B - attach ke server dev yang sudah berjalan
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 --base-url http://127.0.0.1:8000 --no-restart

# Subset stasiun FDSN (default: 5 stasiun di scenarios.json)
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 --no-restart --stations AAFM AAI

# Override tanggal target FDSN (default: otomatis = kemarin, lokal)
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 --no-restart --date 2026-09-10
```

`fdsn_cache_benchmark.py` menerima flag CLI yang sama
(`--base-url`, `--spawn`, `--attach-pid`, `--no-restart`, `--cwd`,
`--out-prefix`, `--stations`, `--date`):

```powershell
.venv\Scripts\python.exe benchmark\fdsn_cache_benchmark.py `
    --attach-pid 12345 --base-url http://127.0.0.1:8000 --no-restart `
    --stations AAFM AAI ABJI
```

Flag lain yang tersedia di kedua script: `--cwd` (working dir untuk
`--spawn`, default root backend) dan `--out-prefix` (prefix nama file hasil,
default timestamp saat dijalankan).

Jumlah stasiun via `--stations` menentukan pembagian skenario campuran di
`fdsn_cache_benchmark.py` (mis. 5 stasiun → 2 cached + 3 uncached untuk
skenario mixed); lihat docstring script untuk aturan lengkapnya.

## `scenarios.json`

Berisi konfigurasi skenario yang dipakai kedua benchmark:

- `fdsn` — parameter waveform FDSN: `network`, `location`, `channels`
  (channel konkret, bukan wildcard `SH*`), `max_lookback_days`,
  `max_points`, dan `stations` (daftar default 5 stasiun; bisa
  disubset via `--stations`). `target_date` **tidak disimpan** di sini —
  kedua script menghitungnya otomatis setiap run (tanggal kemarin waktu
  lokal), kecuali di-override lewat `--date`. Status cached/uncached
  diverifikasi live ke `GET /api/waveform/status` sebelum dipakai.
- `local` — path fixture lokal (`miniseed_path`, `stationxml_path`) yang
  dipakai skenario `local_upload` dan `process_local`.
- `scenarios` — daftar definisi skenario (`id`, `label`, `kind`,
  `operations`). Payload `operations` mengikuti schema di
  `app/models/processing.py` (`TrimOperation`, `FilterOperation`,
  `InstrumentCorrectionOperation`) — struktur ini tidak boleh diubah,
  hanya nilainya yang disesuaikan dengan data yang tersedia.
- `advanced` — konfigurasi channel untuk skenario Spectrogram/PSD/HVSR
  (`spectrogram_channel`, `psd_channel`, `hvsr_channel_n/e/z`); harus diisi
  sesuai nama channel asli pada file lokal, bukan channel FDSN.

File ini adalah **konfigurasi yang boleh disesuaikan** operator sebelum
menjalankan benchmark (lihat `_readme` di dalam file), bukan file yang
di-generate otomatis.

## Fixture di `data/`

- `data/IA.AAFM.mseed` — waveform MiniSEED lokal yang diunggah pada skenario
  `local_upload` dan seluruh skenario `process_local` (trim, filter,
  instrument correction, kombinasinya), dirujuk lewat
  `scenarios.json` → `local.miniseed_path`.
- `data/IA.AAFM.xml` — StationXML pasangan `IA.AAFM.mseed`, dirujuk lewat
  `local.stationxml_path`; dipakai saat skenario butuh instrument response
  (mis. Instrument Correction, HVSR).

## Hasil di `results/`

Setiap run menulis dua file ke `benchmark/results/`, dengan prefix `run_id`
(`--out-prefix` atau timestamp `YYYYMMDD_HHMMSS`):

- `ram_cpu_benchmark.py` menghasilkan `{run_id}_summary.csv` dan
  `{run_id}_raw_timeseries.json`.
- `fdsn_cache_benchmark.py` menghasilkan `{run_id}_fdsn_cache_summary.csv`
  dan `{run_id}_fdsn_cache_raw_timeseries.json`.

File hasil bersifat append-only per run (nama file baru setiap dijalankan);
jangan mengedit atau menghapus file hasil yang sudah ada secara manual —
biarkan sebagai riwayat pengukuran.

## Catatan

- Menjalankan benchmark **tidak mengubah logic aplikasi maupun kode
  benchmark itu sendiri** — script hanya memanggil API dan mencatat hasil.
- Skenario FDSN memerlukan `.env` backend terisi (`BMKG_URL`,
  `BMKG_USERNAME`, `BMKG_PASSWORD`) karena benar-benar memanggil BMKG lewat
  server yang di-benchmark.
- Untuk diagnosa manual per-jam pada satu stasiun/tanggal (di luar konteks
  benchmark), lihat `scripts/diagnose_fdsn_hourly.py` — script itu sengaja
  dipisah dan tidak menyentuh `ram_cpu_benchmark.py` maupun
  `fdsn_cache_benchmark.py`.