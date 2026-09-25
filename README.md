# Interactive Seismogram Viewer — Backend

Backend API untuk **Interactive Seismogram Viewer** menggunakan **FastAPI**.
Backend menangani pengambilan waveform FDSN/BMKG, cache waveform, processing,
local upload, analisis Spectrogram/PSD/HVSR, StationXML, dan export data.

Entry point aplikasi adalah `app/main.py`.

## Quick Start

Jalankan dari **root repository backend**.

### 1. Clone repository

```powershell
git clone https://github.com/rahmatichsan21/interactive-seismogram-viewer-backend.git
cd interactive-seismogram-viewer-backend
```

### 2. Gunakan Python 3.11

Repository ini menggunakan Python 3.11 dan dependency yang dikunci di
`requirements.txt`.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

Verifikasi:

```powershell
python --version
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Siapkan `.env`

Buat file `.env` pada root repository. Variable dasar yang wajib tersedia:

```dotenv
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/seismogram_viewer

BMKG_URL=https://YOUR-FDSN-ENDPOINT
BMKG_USERNAME=YOUR_USERNAME
BMKG_PASSWORD=YOUR_PASSWORD

MAX_DISPLAY_POINTS=2000
CACHE_WINDOW_SECONDS=3600
HOURLY_CACHE_CLEAR_TIME=00:00
```

Nilai credential, host database, dan endpoint FDSN harus diisi sesuai
environment yang digunakan.

### 5. Siapkan database

Buat database MySQL yang sesuai dengan `DATABASE_URL`, lalu jalankan migration
Alembic:

```powershell
python -m alembic upgrade head
```

Verifikasi koneksi:

```powershell
python scripts\check_database.py
```

Repository juga menyediakan `scripts/create_tables.py` sebagai utility manual
yang menggunakan `Base.metadata.create_all()`. Untuk database yang mengikuti
schema versioning repository, gunakan Alembic sebagai langkah database setup.

### 6. Jalankan backend

```powershell
uvicorn app.main:app --reload --port 8000
```

Atau:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Backend tersedia di:

```text
http://127.0.0.1:8000
```

### 7. Verifikasi

Health endpoint:

```text
http://127.0.0.1:8000/health
```

Response:

```json
{
  "status": "ok"
}
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## Prerequisites

- Git
- Python 3.11
- MySQL Server
- Credential dan URL FDSN/BMKG untuk workflow yang mengambil data dari BMKG

Dependency Python tersedia di `requirements.txt`.

---

## Installation

Semua command dijalankan dari root backend, yaitu folder yang berisi:

```text
app/
alembic/
benchmark/
scripts/
data/
storage/
requirements.txt
alembic.ini
README.md
```

### Virtual environment

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

Apabila aktivasi PowerShell diblokir oleh execution policy, virtual environment
tetap dapat digunakan secara langsung:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

dan:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

### Dependencies

Dependency runtime dan tooling ditentukan oleh `requirements.txt`.

Paket utama yang digunakan repository mencakup:

- FastAPI
- Uvicorn
- SQLAlchemy
- PyMySQL
- Alembic
- ObsPy
- NumPy
- SciPy
- pandas
- matplotlib
- Plotly
- hvsrpy
- python-dotenv

Jangan gunakan daftar ini sebagai pengganti `requirements.txt`; file tersebut
tetap menjadi sumber dependency repository.

---

## Environment Configuration

Backend membaca `.env` dari root repository melalui `python-dotenv`.

### Variable wajib

`app/core/config.py` dan `app/core/database.py` saat ini membutuhkan:

| Variable | Fungsi |
| --- | --- |
| `DATABASE_URL` | Connection URL SQLAlchemy untuk MySQL/backend database. |
| `BMKG_URL` | Endpoint FDSN/BMKG yang digunakan ObsPy client. |
| `BMKG_USERNAME` | Username credential FDSN/BMKG. |
| `BMKG_PASSWORD` | Password credential FDSN/BMKG. |
| `MAX_DISPLAY_POINTS` | Batas raw point sebelum temporal-order decimation aktif. |
| `CACHE_WINDOW_SECONDS` | Ukuran window cache waveform. |
| `HOURLY_CACHE_CLEAR_TIME` | Jadwal cleanup harian, format `HH:MM`. |

`DATABASE_URL` divalidasi oleh `app/core/database.py`. Jika tidak ada, aplikasi
gagal dimuat.

`MAX_DISPLAY_POINTS` dan `CACHE_WINDOW_SECONDS` dikonversi ke integer saat
config dimuat.

`HOURLY_CACHE_CLEAR_TIME` divalidasi dalam format `HH:MM` dengan rentang
`00:00`–`23:59`.

### Variable dengan default

Variable berikut memiliki default di `app/core/config.py` sehingga tidak wajib
ditulis di `.env` kecuali ingin men-tuning nilainya:

```dotenv
FDSN_TIMEOUT_SECONDS=20
MAX_DOWNLOAD_ATTEMPTS=3
RETRY_DELAY_SECONDS=2

PROCESSING_CACHE_TTL_SECONDS=300
PROCESSING_CACHE_MAX_ENTRIES=20
PROCESSING_CACHE_MAX_SIZE_BYTES=200000000

RESPONSE_CACHE_TTL_SECONDS=300
RESPONSE_CACHE_MAX_ENTRIES=20

PROCESSING_SWEEP_INTERVAL_SECONDS=60
CACHE_CLEANUP_RETRY_SECONDS=3600

PPSD_LENGTH_SECONDS=300
PPSD_OVERLAP=0.5

PSD_CACHE_TTL_SECONDS=300
PSD_CACHE_MAX_ENTRIES=20

SPECTROGRAM_CACHE_TTL_SECONDS=300
SPECTROGRAM_CACHE_MAX_ENTRIES=20

GAP_THRESHOLD_PERCENT=30

HVSR_WINDOW_SECONDS=60
HVSR_FMIN=0.1
HVSR_FMAX=50
HVSR_REJECTION_ENABLED=false

HVSR_CACHE_TTL_SECONDS=300
HVSR_CACHE_MAX_ENTRIES=20
```

Jangan commit `.env`. File tersebut memang diabaikan oleh Git melalui
`.gitignore`.

---

## Database

Backend menggunakan SQLAlchemy dengan MySQL melalui driver PyMySQL.

### Database URL

`DATABASE_URL` menjadi sumber konfigurasi untuk:

- application database engine;
- script database;
- Alembic.

Contoh format:

```dotenv
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/seismogram_viewer
```

Nama database dapat berbeda, selama sama dengan database yang benar-benar
disiapkan dan URL yang digunakan.

### Alembic

Repository memiliki:

```text
alembic.ini
alembic/
```

`alembic/env.py` membaca `DATABASE_URL` melalui `app.core.database`.

Untuk menjalankan migration:

```powershell
python -m alembic upgrade head
```

### `scripts/create_tables.py`

Utility ini menjalankan:

```python
Base.metadata.create_all(bind=engine)
```

dan dapat dipakai untuk pembuatan tabel langsung dari metadata SQLAlchemy.

Jangan menganggap `create_tables.py` sebagai pengganti versioned migration.
Gunakan Alembic untuk database yang mengikuti migration history repository.

---

## Run Backend

Entry point:

```text
app.main:app
```

Command utama:

```powershell
uvicorn app.main:app --reload --port 8000
```

URL lokal:

```text
http://127.0.0.1:8000
```

CORS pada `app/main.py` mengizinkan frontend lokal:

```text
http://localhost:5173
http://127.0.0.1:5173
```

Saat startup, aplikasi juga membuat background task untuk sweep cache dan daily
waveform cache cleanup.

---

## Verify Backend

### Root endpoint

```text
GET http://127.0.0.1:8000/
```

Response:

```json
{
  "message": "Interactive Seismogram Viewer API"
}
```

### Health endpoint

```text
GET http://127.0.0.1:8000/health
```

Response:

```json
{
  "status": "ok"
}
```

Endpoint `/health` hanya menunjukkan bahwa aplikasi dapat menangani request.
Endpoint tersebut tidak memverifikasi database atau FDSN.

### Import check

Untuk memastikan aplikasi dapat di-import:

```powershell
.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```

Expected output:

```text
Interactive Seismogram Viewer API
```

---

## API Documentation

FastAPI menyediakan dokumentasi OpenAPI:

### Swagger UI

```text
http://127.0.0.1:8000/docs
```

### ReDoc

```text
http://127.0.0.1:8000/redoc
```

### OpenAPI JSON

```text
http://127.0.0.1:8000/openapi.json
```

Gunakan `/docs` untuk melihat parameter request dan response API secara
interaktif.

---

## API Overview

Router yang didaftarkan oleh `app/main.py`:

| Router | Area |
| --- | --- |
| `stations.py` | Station list dan station metadata |
| `waveform.py` | Waveform, cache status, dan waveform download |
| `processing.py` | Processing pipeline |
| `upload.py` | Local MiniSEED/StationXML session |
| `spectrogram.py` | Spectrogram |
| `psd.py` | Power Spectral Density |
| `hvsr.py` | HVSR |
| `download.py` | MiniSEED dan StationXML export |

Endpoint utama:

| Method | Endpoint | Fungsi |
| --- | --- | --- |
| `GET` | `/` | API identity |
| `GET` | `/health` | Application health |
| `GET` | `/api/stations` | Daftar station |
| `GET` | `/api/station-info` | Metadata station |
| `GET` | `/api/waveform` | Ambil waveform |
| `GET` | `/api/waveform/status` | Cek kelengkapan cache waveform |
| `POST` | `/api/waveform/download` | Populasi cache waveform |
| `GET` | `/api/channels` | Channel tersedia |
| `POST` | `/process` | Jalankan processing |
| `POST` | `/api/upload/miniseed` | Upload MiniSEED |
| `POST` | `/api/upload/stationxml` | Upload StationXML |
| `GET` | `/api/upload/stationxml/{session_id}/validation` | Validasi StationXML |
| `GET` | `/api/upload/{session_id}/waveform` | Waveform dari upload session |
| `GET` | `/api/spectrogram` | Generate spectrogram |
| `GET` | `/api/psd` | Generate PSD |
| `GET` | `/api/hvsr` | Generate HVSR |
| `POST` | `/api/download/miniseed` | Export MiniSEED |
| `GET` | `/api/download/stationxml` | Download StationXML |

Detail parameter dan contract tetap dimiliki dokumentasi router dan models.

---

## Architecture Overview

Alur runtime utama:

```text
HTTP Request
    ↓
FastAPI Router
    ↓
Service
    ↓
FDSN / Local Upload / Cache
    ↓
Processing atau Analysis
    ↓
JSON / image / file response
```

Folder utama:

```text
app/
├── main.py
├── core/
├── models/
├── routers/
├── services/
└── processing/

alembic/
benchmark/
scripts/
data/
storage/
```

### Core

`app/core/` menangani configuration, database, FDSN client, dan logging.

Detail:
[app/core/README.md](app/core/README.md)

### Models

`app/models/` mendefinisikan SQLAlchemy model dan Pydantic contract.

Detail:
[app/models/README.md](app/models/README.md)

### Routers

`app/routers/` merupakan HTTP boundary FastAPI.

Detail:
[app/routers/README.md](app/routers/README.md)

### Services

`app/services/` berisi domain logic, integrasi FDSN, storage/cache, processing
support, analysis, upload, dan export.

Detail:
[app/services/README.md](app/services/README.md)

### Processing

`app/processing/` berisi registry, pipeline, dan operation processing.

Detail:
[app/processing/README.md](app/processing/README.md)

### Scripts

Manual utility, diagnostic, validation, dan experimental tools.

Detail:
[scripts/README.md](scripts/README.md)

### Benchmark

Benchmark performa backend dan skenario pengukuran.

Detail:
[benchmark/README.md](benchmark/README.md)

---

## Feature Overview

Backend saat ini mencakup:

- waveform FDSN/BMKG;
- raw waveform cache;
- local MiniSEED upload;
- local StationXML upload;
- waveform processing;
- Spectrogram;
- PSD;
- HVSR;
- StationXML instrument response;
- MiniSEED export.

Detail implementasi feature berada pada README folder owner masing-masing.

---

## Data and Storage Overview

### Station list

Daftar station aplikasi berada di:

```text
data/stations.csv
```

Penambahan station dilakukan melalui utility:

```powershell
python scripts\add_station_csv.py --station GTOI
```

Detail behavior utility:
[scripts/README.md](scripts/README.md)

### Raw waveform cache

Raw waveform cache menggunakan:

- `WaveformRecord` di MySQL;
- file MiniSEED di `storage/waveforms/`.

### Instrument response cache

Persistent response StationXML berada di:

```text
storage/responses/
```

### Runtime cache

Processing dan image analysis menggunakan cache in-memory dengan TTL/LRU.

Detail lifecycle cache:
[app/services/README.md](app/services/README.md)

---

## Troubleshooting

### Database gagal terhubung

Periksa:

```text
DATABASE_URL
MySQL Server
database name
host/port
username/password
```

Kemudian:

```powershell
python scripts\check_database.py
```

### `DATABASE_URL is not defined in the .env file`

Buat `.env` di root backend dan isi `DATABASE_URL`.

### `HOURLY_CACHE_CLEAR_TIME` invalid

Gunakan format:

```dotenv
HOURLY_CACHE_CLEAR_TIME=00:00
```

Format harus dua digit `HH:MM` dalam rentang `00:00`–`23:59`.

### FDSN/BMKG gagal

Periksa:

```text
BMKG_URL
BMKG_USERNAME
BMKG_PASSWORD
```

Kemudian pastikan koneksi network dan data request memang tersedia.

### PowerShell tidak mengizinkan aktivasi virtual environment

Gunakan executable `.venv` secara langsung:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

---

## Documentation Index

| Dokumentasi | Fokus |
| --- | --- |
| [app/core/README.md](app/core/README.md) | Configuration, database, FDSN client, logging |
| [app/models/README.md](app/models/README.md) | Data model dan API contract |
| [app/routers/README.md](app/routers/README.md) | Router dan endpoint detail |
| [app/services/README.md](app/services/README.md) | Service, waveform, cache, storage, analysis, export |
| [app/processing/README.md](app/processing/README.md) | Pipeline dan operation processing |
| [scripts/README.md](scripts/README.md) | Manual scripts, diagnostics, validation |
| [benchmark/README.md](benchmark/README.md) | Performance benchmark |
| [alembic/README](alembic/README) | Alembic boilerplate directory note |

---

## Project Notes

- `.env` tidak boleh di-commit.
- `storage/` berisi runtime/cache data yang diabaikan oleh Git sesuai
  `.gitignore`.
- `scripts/` bukan bagian dari FastAPI runtime.
- `benchmark/` adalah tooling pengukuran performa yang terpisah dari request
  runtime.
- Untuk detail implementation, selalu gunakan README folder owner sebagai
  sumber dokumentasi detail.
