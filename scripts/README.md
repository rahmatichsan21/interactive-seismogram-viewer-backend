# `scripts`

Folder ini berisi utility manual yang dijalankan langsung dengan Python.
Script di sini bukan bagian dari FastAPI runtime dan tidak dijalankan otomatis
oleh aplikasi.

## Cara menjalankan

Jalankan dari root backend:

```powershell
.venv\Scripts\python.exe scripts\<nama_script>.py
```

Jika script menyediakan CLI:

```powershell
.venv\Scripts\python.exe scripts\<nama_script>.py --help
```

Sebagian besar script menggunakan modul `app/`, tetapi
`test_obspy_aafm_gap_processing.py` memakai ObsPy FDSN client secara langsung.

---

## Risiko

| Label | Arti |
| --- | --- |
| **READ-ONLY** | Hanya membaca data. |
| **NETWORK** | Melakukan request FDSN/BMKG. |
| **LIVE DATABASE** | Berinteraksi dengan database environment aktif. |
| **FILE WRITE** | Menulis file lokal. |
| **DESTRUCTIVE** | Dapat menghapus data cache/database. |

Sebelum memakai script `LIVE DATABASE` atau `DESTRUCTIVE`, pastikan `.env`
menunjuk ke environment yang benar.

---

## Setup

### `create_tables.py`

Membuat tabel SQLAlchemy melalui:

```text
Base.metadata.create_all(bind=engine)
```

**Risiko:** `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\create_tables.py
```

### `check_database.py`

Memeriksa koneksi database dan database yang sedang digunakan.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\check_database.py
```

---

## Station CSV

### `add_station_csv.py`

Menambahkan satu atau beberapa station ke `stations.csv` existing tanpa
regenerate atau overwrite seluruh file.

Contoh:

```powershell
.venv\Scripts\python.exe scripts\add_station_csv.py --station GTOI
```

```powershell
.venv\Scripts\python.exe scripts\add_station_csv.py --station GTOI AAII PAGA KUKI
```

Behavior:

- membaca station existing;
- skip duplicate;
- mengambil metadata FDSN level station;
- membaca `start_date`;
- menggunakan window historis satu hari setelah `start_date`;
- mengecek akses waveform pada window 60 detik;
- `NoData` dianggap credential diterima;
- `401/403` dianggap akses ditolak;
- error teknis tidak dianggap Unauthorized;
- station yang lolos ditambahkan dengan mode append.

Jika file belum ada, header dibuat:

```text
net,kode_stasiun
```

**Risiko:** `NETWORK`, `FILE WRITE`

### Catatan legacy

Nama lama:

```text
generate_station_csv.py
```

bukan file aktif pada tree `main` saat ini. Utility aktif untuk penambahan
station adalah:

```text
add_station_csv.py
```

---

## Maintenance

### `cleanup_cache.py`

Menjalankan cleanup cache waveform secara manual.

**Risiko:** `DESTRUCTIVE`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\cleanup_cache.py
```

### `clear_all_cache.py`

Menghapus seluruh cache waveform pada database dan file cache.

**Risiko:** `DESTRUCTIVE`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\clear_all_cache.py
```

---

## Diagnostic

### `diagnose_cache.py`

Inspeksi row `WaveformRecord` untuk window hardcode yang ditentukan script.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\diagnose_cache.py
```

### `diagnose_aafm_gap.py`

Inspeksi gap cache `IA.AAFM` pada window hardcode dan menampilkan trace/gap
sebelum dan sesudah merge.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\diagnose_aafm_gap.py
```

### `diagnose_fdsn_hourly.py`

Diagnosa kelengkapan cache per jam untuk station/tanggal/channel tertentu.
Dengan `--check-fdsn`, script juga memeriksa FDSN/BMKG untuk window yang tidak
lengkap.

Contoh:

```powershell
.venv\Scripts\python.exe scripts\diagnose_fdsn_hourly.py --station AAFM --date 2026-09-08
```

**Risiko tanpa `--check-fdsn`:** `READ-ONLY`, `LIVE DATABASE`

**Risiko dengan `--check-fdsn`:** `READ-ONLY`, `LIVE DATABASE`, `NETWORK`

---

## Validation

### `verify_temporal.py`

Memverifikasi decimation temporal-order pada waveform FDSN.

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\verify_temporal.py
```

### `smoke_test_processing.py`

Smoke test operation `trim` melalui processing service.

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\smoke_test_processing.py
```

---

## Development / Manual Test

Script berikut digunakan untuk testing, reproduksi issue, atau eksperimen
manual. Tidak ada yang dijalankan otomatis oleh FastAPI runtime.

### `test_hourly_cache.py`

Skenario manual hourly cache.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `DESTRUCTIVE`, `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_hourly_cache.py
```

### `test_processing_cache.py`

Skenario `ProcessingCache` versi awal.

**Status:** `D — POSSIBLY LEGACY / SUPERSEDED`

Masih dapat dijalankan, tetapi ada `test_processing_cache_v2.py` sebagai varian
yang lebih baru/berbeda. Tidak ditemukan pemanggilan runtime terhadap script
ini.

**Risiko:** `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_processing_cache.py
```

### `test_processing_cache_v2.py`

Skenario manual `ProcessingCache` varian Hybrid A+D.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_processing_cache_v2.py
```

### `test_seen_channels.py`

Test manual `get_seen_channels()`.

Script membersihkan cache sebagai bagian dari skenario.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `DESTRUCTIVE`, `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_seen_channels.py
```

### `test_obspy_aafm_gap_processing.py`

Eksperimen langsung dengan `obspy.clients.fdsn.Client` untuk gap/processing
pada `IA.AAFM`.

**Status:** `C — DEVELOPMENT / EXPERIMENTAL`

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\test_obspy_aafm_gap_processing.py
```

### `visual_compare.py`

Eksperimen visual perbandingan raw, envelope min/max, temporal-order, dan
bucket mean. Output `visual_compare.png` ditulis ke root backend.

**Status:** `C — DEVELOPMENT / EXPERIMENTAL`

**Risiko:** `NETWORK`, `FILE WRITE`

```powershell
.venv\Scripts\python.exe scripts\visual_compare.py
```

---

## Status classification

| Status | Arti |
| --- | --- |
| **B — MANUAL UTILITY** | Setup, maintenance, atau diagnostic yang masih punya fungsi operasional. |
| **C — DEVELOPMENT / TESTING / EXPERIMENTAL** | Testing, validasi, reproduksi issue, atau eksperimen. |
| **D — POSSIBLY LEGACY / SUPERSEDED** | Masih ada dan runnable tetapi ada indikasi kuat bahwa varian/implementasi lebih baru mengambil alih. |
| **E — CONFIRMED UNUSED** | Tidak ditemukan penggunaan tersisa dan tidak ada fungsi manual yang terdokumentasi untuk dipertahankan. |

Tidak ada script pada tree `main` yang dapat dipastikan **E** hanya dari audit
repository ini.

---

## General notes

- Script hardcode tertentu dapat bergantung pada station/channel/date tertentu.
- Script bukan pengganti automated test suite.
- Script destructive harus diperlakukan sebagai operasi terhadap live data.
- `scripts/README.md` adalah sumber detail untuk utility pada folder `scripts`.
