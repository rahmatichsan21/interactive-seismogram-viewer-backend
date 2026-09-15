# Backend

Backend menyediakan API FastAPI untuk waveform, processing, upload lokal,
analisis, download, dan cache. Entry point aplikasi adalah `app/main.py`.

## Menjalankan

Jalankan dari folder ini:

```powershell
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

API berjalan pada `http://127.0.0.1:8000`; endpoint dasar adalah `/` dan
`/health`.

## Prasyarat

- Python 3.11 dan dependency pada `requirements.txt`.
- MySQL lokal dengan database `seismogram_viewer`.
- File `.env` di root backend; jangan commit file ini.
- Kredensial dan URL BMKG FDSN untuk workflow FDSN.

Minimal `.env` memuat `DATABASE_URL`, `BMKG_URL`, `BMKG_USERNAME`,
`BMKG_PASSWORD`, `MAX_DISPLAY_POINTS`, `CACHE_WINDOW_SECONDS`, dan
`HOURLY_CACHE_CLEAR_TIME`. Parameter cache, PSD, HVSR, serta
`GAP_THRESHOLD_PERCENT` dibaca dari `app/core/config.py`.

Setup database:

```powershell
.venv\Scripts\python.exe scripts\create_tables.py
.venv\Scripts\python.exe scripts\check_database.py
```

## Struktur

```text
app/
├── main.py        # FastAPI app, CORS, router, startup cache jobs
├── core/          # konfigurasi, database, FDSN client, logging
├── models/        # SQLAlchemy dan Pydantic contract
├── routers/       # HTTP endpoint
├── services/      # waveform, cache, upload, PSD, HVSR, StationXML
└── processing/    # registry dan operation pipeline ObsPy
scripts/           # setup, maintenance, diagnostic, validation manual
benchmark/         # benchmark RAM/CPU dan cache FDSN
data/stations.csv  # daftar station aplikasi
storage/           # cache runtime; tidak untuk source control
```

Dokumentasi module: [core](app/core/README.md), [models](app/models/README.md),
[routers](app/routers/README.md), [services](app/services/README.md), dan
[processing](app/processing/README.md).

## Arsitektur runtime

1. Router menerima request dan memvalidasi parameter HTTP.
2. Service mengambil waveform dari local upload session atau provider FDSN.
3. Raw waveform cache menggunakan record MySQL dan MiniSEED di
   `storage/waveforms/`.
4. Processing service menjalankan operation per identity trace.
5. Trace diserialisasi pada resolusi tampilan sebelum dikembalikan ke frontend.

### Waveform, gap, dan processing

Assembly mempertahankan gap sebagai masked trace. Untuk operation ObsPy,
workflow adalah `merge(fill_value=None)` → `split()` → process tiap segmen →
`merge(fill_value=0)`. Gap tidak boleh menghasilkan timestamp `NaN` pada JSON.

Operation saat ini: `trim`, `filter`, dan `instrument_correction`. Tambahan
operation memerlukan model request, handler, registry, dan adapter frontend.
Processing berjalan sequential per trace agar penggunaan RAM terbatas.

### StationXML dan cache

- FDSN memakai persistent instrument response cache per network/station.
- Local upload dapat menyimpan beberapa StationXML dalam satu session; inventory
  digabung ketika validasi atau Instrument Correction.
- Response dicocokkan per trace: network, station, location, channel, waktu.
- Raw waveform memakai MySQL + MiniSEED; processing dan image analisis memakai
  cache RAM TTL/LRU.

## Router API

`stations.py`, `waveform.py`, `processing.py`, `upload.py`, `spectrogram.py`,
`psd.py`, `hvsr.py`, dan `download.py` didaftarkan oleh `app/main.py`.

Lihat [scripts](scripts/README.md) untuk tools manual dan
[benchmark](benchmark/README.md) untuk benchmark yang dipertahankan terpisah.
