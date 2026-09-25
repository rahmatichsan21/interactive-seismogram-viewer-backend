# `benchmark`

Folder `benchmark` berisi tooling untuk mengukur performa backend dari luar
application runtime.

Benchmark mengirim request HTTP nyata ke server FastAPI dan mengukur waktu serta
resource process, termasuk RSS memory dan CPU. Benchmark bukan unit test.

## Benchmark yang tersedia

| Script | Tujuan |
| --- | --- |
| `ram_cpu_benchmark.py` | Benchmark 22 skenario yang mencakup Local Upload/Processing, FDSN/cache, Spectrogram, PSD, dan HVSR. |
| `fdsn_cache_benchmark.py` | Retest khusus skenario FDSN cached/uncached/multi/mixed. |

---

## Endpoint yang digunakan

Benchmark memakai endpoint yang memang tersedia di backend:

```text
GET /api/waveform
GET /api/waveform/status
POST /api/upload/miniseed
POST /api/upload/stationxml
GET /api/upload/{session_id}/waveform
DELETE /api/upload/{session_id}
POST /process
GET /api/spectrogram
GET /api/psd
GET /api/hvsr
```

Benchmark tidak membuat endpoint baru.

---

## Menjalankan benchmark

Dijalankan dari root backend dengan virtual environment aktif.

Kedua benchmark mendukung dua mode:

```text
spawn
attach
```

### Spawn

Script menjalankan server yang akan diukur.

Contoh `ram_cpu_benchmark.py`:

```powershell
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --spawn "uvicorn app.main:app --host 127.0.0.1 --port 8000" `
    --base-url http://127.0.0.1:8000
```

### Attach

Menempel ke process server yang sudah berjalan:

```powershell
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 `
    --base-url http://127.0.0.1:8000 `
    --no-restart
```

`12345` adalah contoh PID process; gunakan PID server yang benar saat
menjalankan benchmark.

### Subset station

```powershell
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 `
    --no-restart `
    --stations AAFM AAI
```

### Override tanggal FDSN

```powershell
.venv\Scripts\python.exe benchmark\ram_cpu_benchmark.py `
    --attach-pid 12345 `
    --no-restart `
    --date 2026-09-10
```

### `fdsn_cache_benchmark.py`

```powershell
.venv\Scripts\python.exe benchmark\fdsn_cache_benchmark.py `
    --attach-pid 12345 `
    --base-url http://127.0.0.1:8000 `
    --no-restart `
    --stations AAFM AAI ABJI
```

Flag umum:

```text
--base-url
--spawn
--attach-pid
--no-restart
--cwd
--out-prefix
--stations
--date
```

---

## `scenarios.json`

File:

```text
benchmark/scenarios.json
```

menyediakan konfigurasi benchmark untuk kedua script.

### `fdsn`

Berisi konfigurasi seperti:

```text
network
location
channels
max_lookback_days
max_points
stations
```

Tanggal target tidak disimpan sebagai nilai tetap; script menghitung target date
secara runtime dan dapat di-override dengan `--date`.

Status cached/uncached diverifikasi live melalui endpoint:

```text
GET /api/waveform/status
```

### `local`

Menentukan fixture:

```text
miniseed_path
stationxml_path
```

untuk skenario local upload/processing.

### `scenarios`

Mendefinisikan skenario dan `operations` yang menggunakan model processing:

```text
TrimOperation
FilterOperation
InstrumentCorrectionOperation
```

### `advanced`

Mengatur channel yang digunakan oleh skenario:

```text
spectrogram_channel
psd_channel
hvsr_channel_n
hvsr_channel_e
hvsr_channel_z
```

Channel harus sesuai data fixture lokal untuk skenario local analysis.

---

## Fixture

Fixture benchmark berada di:

```text
benchmark/data/
```

Saat ini:

```text
benchmark/data/IA.AAFM.mseed
benchmark/data/IA.AAFM.xml
```

MiniSEED digunakan untuk local upload/processing.

StationXML digunakan pada skenario yang membutuhkan instrument response, seperti
Instrument Correction dan HVSR.

---

## Results

Hasil benchmark ditulis ke:

```text
benchmark/results/
```

Dengan prefix `run_id`.

### `ram_cpu_benchmark.py`

Menghasilkan:

```text
{run_id}_summary.csv
{run_id}_raw_timeseries.json
```

### `fdsn_cache_benchmark.py`

Menghasilkan:

```text
{run_id}_fdsn_cache_summary.csv
{run_id}_fdsn_cache_raw_timeseries.json
```

Hasil benchmark dimaksudkan sebagai riwayat pengukuran per run.

---

## Relationship dengan application

```text
FastAPI application
        ↑
    HTTP requests
        ↑
benchmark scripts
```

Benchmark mengukur application runtime yang sudah ada. Logic benchmark
terpisah dari router/service production.

Untuk request contract:
[app/models/README.md](../app/models/README.md)

Untuk router:
[app/routers/README.md](../app/routers/README.md)

---

## Requirements

Skenario FDSN membutuhkan environment backend yang valid:

```text
BMKG_URL
BMKG_USERNAME
BMKG_PASSWORD
```

Skenario local menggunakan fixture pada `benchmark/data/`.

Server FastAPI harus dapat dijalankan pada base URL yang dipakai benchmark.

---

## Notes

- Benchmark bukan unit test.
- Benchmark mengirim request nyata.
- Pastikan backend yang diukur menggunakan environment/configuration yang
  memang ingin diukur.
- Skenario dapat dipengaruhi availability FDSN dan state cache.
- Jangan menginterpretasikan satu hasil benchmark sebagai jaminan universal
  terhadap semua environment.
