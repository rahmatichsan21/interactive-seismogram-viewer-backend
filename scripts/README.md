# `scripts`

Folder ini berisi tools manual yang dijalankan langsung dengan Python. Script
di folder ini **bukan bagian dari runtime FastAPI** dan tidak dijalankan otomatis
oleh aplikasi.

Kegunaannya meliputi:

- setup database awal;
- maintenance dan pembersihan cache waveform;
- diagnosis database, cache, dan FDSN;
- validasi manual processing/decimation;
- eksperimen dan reproduksi masalah tertentu.

Jalankan script dari **root repository backend**, yaitu folder yang berisi
`app/`, `scripts/`, `alembic/`, dan file konfigurasi backend.

Contoh umum di Windows:

```powershell
.venv\Scripts\python.exe scripts\<nama_script>.py
```

Untuk script yang menyediakan opsi CLI:

```powershell
.venv\Scripts\python.exe scripts\<nama_script>.py --help
```

> Catatan: sebagian besar script menggunakan modul dari `app/`, tetapi tidak
> semuanya. `test_obspy_aafm_gap_processing.py` menggunakan client FDSN dari
> ObsPy secara langsung.

---

## Legenda risiko

| Label | Arti |
| --- | --- |
| **READ-ONLY** | Hanya membaca data; tidak sengaja mengubah state database/cache. |
| **NETWORK** | Melakukan request ke FDSN/BMKG atau layanan jaringan lain. |
| **LIVE DATABASE** | Berinteraksi dengan database yang dikonfigurasi pada environment saat script dijalankan. |
| **FILE WRITE** | Membuat atau menulis file di filesystem lokal. |
| **DESTRUCTIVE** | Dapat menghapus data database dan/atau file cache secara permanen. |

> Sebelum menjalankan script dengan **LIVE DATABASE** atau **DESTRUCTIVE**,
> pastikan `.env` menunjuk ke database/environment yang benar.

---

## Peringatan: script yang dapat mengubah atau menghapus cache/database

Script berikut **bukan read-only**:

- `cleanup_cache.py` — menjalankan rutin cleanup cache secara manual;
- `clear_all_cache.py` — menghapus seluruh cache waveform;
- `test_hourly_cache.py` — membersihkan cache sebagai bagian dari skenario test;
- `test_seen_channels.py` — membersihkan cache sebagai bagian dari skenario test.

Jangan jalankan script tersebut pada environment yang datanya masih
diperlukan tanpa memastikan dampaknya terlebih dahulu.

---

# Setup

## `create_tables.py`

Membuat tabel SQLAlchemy dengan `Base.metadata.create_all()` pada database
yang dikonfigurasi oleh backend.

**Risiko:** `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\create_tables.py
```

## `check_database.py`

Memeriksa koneksi database dan menampilkan informasi database yang sedang
digunakan. Script ini bersifat read-only.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\check_database.py
```

---

# Station CSV

## `add_station_csv.py`

Digunakan untuk **menambahkan station baru** ke `stations.csv` yang sudah ada.

Script ini **tidak melakukan regenerate seluruh CSV** dan **tidak menimpa
station yang sudah ada**.

### Cara pakai

Satu station:

```powershell
.venv\Scripts\python.exe scripts\add_station_csv.py --station GTOI
```

Beberapa station sekaligus:

```powershell
.venv\Scripts\python.exe scripts\add_station_csv.py --station GTOI AAII PAGA KUKI
```

### Perilaku aktual script

`--station` wajib diisi dan menerima satu atau lebih kode station.

Sebelum menambahkan data, script:

1. membaca `STATION_CSV` yang sudah ada;
2. membentuk set `(network, kode_stasiun)` untuk mendeteksi duplikasi;
3. melewati station yang sudah tercatat;
4. mengambil metadata station dari FDSN dengan `level="station"`;
5. mengambil `start_date` dari metadata station;
6. membentuk window pengecekan historis:
   - mulai **1 hari setelah `start_date`**;
   - panjang window **60 detik**;
7. memanggil `get_waveforms()` untuk station tersebut;
8. hanya menambahkan station apabila hasil pengecekan menyatakan akses
   diterima.

### Arti hasil pengecekan FDSN

Script membedakan tiga kondisi:

| Hasil internal | Arti | Tindakan |
| --- | --- | --- |
| `True` | Credential diterima; termasuk kondisi `FDSNNoDataException` | Station ditambahkan |
| `False` | Server secara eksplisit mengembalikan `401 Unauthorized` atau `403 Forbidden` | Station tidak ditambahkan |
| `None` | Error teknis seperti timeout/koneksi/parsing | Station tidak ditambahkan; perlu dicek ulang |

`FDSNNoDataException` tidak dianggap sebagai penolakan akses karena server
sudah menerima request, tetapi tidak memberikan data pada window yang diminta.

### Penulisan CSV

Jika `stations.csv` belum ada, script membuat header:

```text
net,kode_stasiun
```

Kemudian station baru ditulis dengan mode append.

Contoh:

```text
net,kode_stasiun
IA,AAFM
IA,GTOI
```

Station yang sudah ada tidak ditulis ulang. Setelah satu station berhasil
ditambahkan, station tersebut juga dicatat di set internal agar duplikasi
dalam satu pemanggilan CLI tidak terjadi.

**Risiko:** `NETWORK`, `FILE WRITE`

### Catatan

Script ini menggunakan konfigurasi FDSN backend melalui `app.core.config` dan
client FDSN dari `app.core.fdsn_client`. Oleh karena itu konfigurasi URL dan
credential FDSN pada `.env` harus valid.

---

# Maintenance

## `cleanup_cache.py`

Menjalankan `run_waveform_cache_cleanup()` secara manual, yaitu rutin cleanup
cache waveform yang juga digunakan oleh scheduler aplikasi.

Script ini berguna ketika cleanup ingin dipicu segera tanpa menunggu scheduler.

**Risiko:** `DESTRUCTIVE`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\cleanup_cache.py
```

## `clear_all_cache.py`

Menghapus seluruh cache waveform:

- row `WaveformRecord` pada database;
- file MiniSEED pada `storage/waveforms/`;
- termasuk file cache yang tidak lagi memiliki row terkait di database.

Script ini bersifat destruktif.

**Risiko:** `DESTRUCTIVE`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\clear_all_cache.py
```

---

# Diagnostic

Script pada bagian ini digunakan untuk melihat kondisi database/cache secara
manual. Kecuali disebutkan lain, script diagnostic tidak dimaksudkan untuk
mengubah data.

## `diagnose_cache.py`

Menampilkan row `WaveformRecord` yang cocok dengan window hardcode:

- network: `IA`
- station: `AAI`
- start: `2025-07-01 00:00:00`
- end: `2025-07-02 00:00:00`

Output menampilkan jumlah row dan informasi seperti location, channel,
`created_at`, dan path file cache.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\diagnose_cache.py
```

## `diagnose_aafm_gap.py`

Mendiagnosis gap pada cache lokal untuk:

- network/station: `IA.AAFM`
- channel: `SH*`
- window: `2026-09-03 00:00:00` sampai `2026-09-03 04:00:00`

Script memeriksa setiap hourly window dari cache, lalu menampilkan:

- trace count;
- start/end time;
- sampling rate;
- jumlah sample;
- apakah data merupakan masked array;
- jumlah sample masked;
- finite/non-finite data;
- gap sebelum `merge()`;
- gap setelah `merge()`.

**Risiko:** `READ-ONLY`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\diagnose_aafm_gap.py
```

## `diagnose_fdsn_hourly.py`

Mendiagnosis cache per jam untuk station, tanggal, dan channel tertentu.

Script membandingkan:

- row cache yang ada di database;
- keberadaan file MiniSEED yang dirujuk row cache;
- kondisi cache yang tidak lengkap/broken.

Dengan `--check-fdsn`, script juga dapat melakukan pengecekan langsung ke
FDSN/BMKG untuk jam yang cache-nya tidak lengkap. Hasil pengecekan FDSN tidak
disimpan oleh script ini.

Contoh:

```powershell
.venv\Scripts\python.exe scripts\diagnose_fdsn_hourly.py --station AAFM --date 2026-09-08
```

Dengan network dan channel eksplisit:

```powershell
.venv\Scripts\python.exe scripts\diagnose_fdsn_hourly.py --network IA --station AAFM --date 2026-09-08 --channels SHZ SHE SHN --check-fdsn
```

Tanpa `--check-fdsn`, script tidak perlu melakukan request FDSN tambahan.

**Risiko tanpa `--check-fdsn`:** `READ-ONLY`, `LIVE DATABASE`

**Risiko dengan `--check-fdsn`:** `READ-ONLY`, `LIVE DATABASE`, `NETWORK`

---

# Validation

Script pada bagian ini digunakan untuk validasi manual perilaku backend.
Script-script tersebut **bukan automated test suite `pytest`**.

## `verify_temporal.py`

Memverifikasi perilaku decimation temporal-order pada waveform `IA.AAFM`,
termasuk kondisi di bawah dan di atas `MAX_DISPLAY_POINTS`.

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\verify_temporal.py
```

## `smoke_test_processing.py`

Smoke test untuk operation `trim` melalui `apply_pipeline` menggunakan
waveform FDSN `IA.AAFM`.

Script menampilkan kondisi stream sebelum dan sesudah processing.

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\smoke_test_processing.py
```

---

# Experimental / Manual Test

Bagian ini berisi script yang dibuat untuk pengujian atau investigasi pada
titik tertentu selama pengembangan.

Script di bagian ini:

- tidak dijalankan otomatis oleh aplikasi;
- tidak dijalankan sebagai CI regression test;
- dapat memiliki station/date/channel hardcode;
- hasilnya tidak otomatis menjamin seluruh backend benar.

## `test_hourly_cache.py`

Skenario manual untuk perilaku hourly cache, termasuk exact window dan cleanup.

Script melakukan pembersihan cache sebagai bagian dari setup/skenario test.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `DESTRUCTIVE`, `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_hourly_cache.py
```

## `test_processing_cache.py`

Skenario manual untuk `ProcessingCache`, termasuk snapshot prefix processing,
undo/redo processing, dan perbedaan cache berdasarkan channel.

Script ini menggunakan data waveform dan database session untuk menjalankan
skenario cache secara manual.

**Status:** `D — POSSIBLY LEGACY / SUPERSEDED`

Artinya script masih dapat dijalankan, tetapi ada varian
`test_processing_cache_v2.py` yang berisi skenario `ProcessingCache` yang lebih
baru/berbeda. Tidak ada bukti bahwa script ini dipanggil oleh runtime,
CI, Docker, atau benchmark otomatis.

**Risiko:** `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_processing_cache.py
```

## `test_processing_cache_v2.py`

Varian manual `ProcessingCache` dengan skenario yang disebut pada script sebagai
`Hybrid A+D`.

Script ini digunakan sebagai test/reproduksi manual dan tidak dipanggil oleh
runtime aplikasi.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_processing_cache_v2.py
```

## `test_seen_channels.py`

Skenario manual untuk perilaku `get_seen_channels()` sebagai sumber informasi
channel yang telah terlihat pada cache.

Script membersihkan cache pada beberapa tahap sebagai bagian dari skenario
pengujian.

**Status:** `C — DEVELOPMENT / TESTING`

**Risiko:** `DESTRUCTIVE`, `NETWORK`, `LIVE DATABASE`

```powershell
.venv\Scripts\python.exe scripts\test_seen_channels.py
```

---

# Gap / ObsPy Experiment

## `test_obspy_aafm_gap_processing.py`

Eksperimen langsung menggunakan `obspy.clients.fdsn.Client`, bukan service
waveform backend.

Tujuan script adalah menyelidiki workflow:

```text
FDSN download
    ↓
merge dengan gap dipertahankan
    ↓
analisis gap
    ↓
split
    ↓
filter / instrument correction
    ↓
merge
```

Konfigurasi eksperimen saat ini menggunakan:

- network: `IA`
- station: `AAFM`
- channel: `SH*`
- window: `2026-09-03 00:00:00` sampai `2026-09-03 04:00:00`
- threshold gap: `30%`

Script membaca credential FDSN langsung dari `.env`.

**Status:** `C — DEVELOPMENT / EXPERIMENTAL`

**Risiko:** `NETWORK`

```powershell
.venv\Scripts\python.exe scripts\test_obspy_aafm_gap_processing.py
```

---

# Visual Comparison

## `visual_compare.py`

Membandingkan tiga pendekatan representasi waveform terhadap data raw:

1. envelope min/max;
2. temporal-order min/max;
3. bucket mean.

Script:

- mengunduh waveform `IA.AAFM.SHZ`;
- memakai window `2025-07-01T00:00:00` sampai `2025-07-01T01:41:00`;
- menghitung decimation berdasarkan `DECIMATION_DURATION_SECONDS`;
- menghitung bucket;
- membuat plot perbandingan;
- menyimpan hasil sebagai `visual_compare.png` di root backend.

**Status:** `C — DEVELOPMENT / EXPERIMENTAL`

**Risiko:** `NETWORK`, `FILE WRITE`

```powershell
.venv\Scripts\python.exe scripts\visual_compare.py
```

Output file:

```text
visual_compare.png
```

---

# Ringkasan status script

| Script | Status | Fungsi utama |
| --- | --- | --- |
| `add_station_csv.py` | **B — MANUAL UTILITY** | Menambahkan station baru ke `stations.csv` secara append |
| `check_database.py` | **B — MANUAL UTILITY** | Cek koneksi database |
| `cleanup_cache.py` | **B — MANUAL UTILITY** | Menjalankan cleanup cache secara manual |
| `clear_all_cache.py` | **B — MANUAL UTILITY** | Mengosongkan seluruh cache |
| `create_tables.py` | **B — MANUAL UTILITY** | Membuat tabel database |
| `diagnose_cache.py` | **B — MANUAL UTILITY** | Inspeksi row cache tertentu |
| `diagnose_aafm_gap.py` | **B — MANUAL UTILITY** | Inspeksi gap pada cache `IA.AAFM` |
| `diagnose_fdsn_hourly.py` | **B — MANUAL UTILITY** | Diagnosa cache per jam dan opsi verifikasi FDSN |
| `smoke_test_processing.py` | **C — DEVELOPMENT / TESTING** | Smoke test processing `trim` |
| `test_hourly_cache.py` | **C — DEVELOPMENT / TESTING** | Skenario hourly cache |
| `test_processing_cache.py` | **D — POSSIBLY LEGACY / SUPERSEDED** | Skenario `ProcessingCache` versi awal |
| `test_processing_cache_v2.py` | **C — DEVELOPMENT / TESTING** | Skenario `ProcessingCache` varian Hybrid A+D |
| `test_seen_channels.py` | **C — DEVELOPMENT / TESTING** | Skenario `get_seen_channels()` |
| `test_obspy_aafm_gap_processing.py` | **C — DEVELOPMENT / EXPERIMENTAL** | Eksperimen gap/processing langsung dengan ObsPy |
| `verify_temporal.py` | **C — DEVELOPMENT / TESTING** | Verifikasi decimation temporal-order |
| `visual_compare.py` | **C — DEVELOPMENT / EXPERIMENTAL** | Visual comparison beberapa algoritma decimation |

### Arti status

| Status | Arti |
| --- | --- |
| **A — ACTIVE** | Dipanggil sebagai bagian dari runtime/application flow otomatis. |
| **B — MANUAL UTILITY** | Script manual yang masih punya fungsi operasional/setup/diagnostic yang jelas. |
| **C — DEVELOPMENT / TESTING / EXPERIMENTAL** | Script untuk testing, validasi, reproduksi issue, atau eksperimen pengembangan. |
| **D — POSSIBLY LEGACY / SUPERSEDED** | Masih ada dan dapat dijalankan, tetapi ada indikasi kuat bahwa penggunaannya sudah digantikan/ditinggalkan oleh varian atau implementasi yang lebih baru. |
| **E — CONFIRMED UNUSED** | Tidak ditemukan penggunaan yang tersisa dan tidak ada fungsi manual yang terdokumentasi untuk dipertahankan. |

> **Catatan:** klasifikasi di atas adalah klasifikasi fungsi script saat ini.
> Status `D` tidak berarti file harus langsung dihapus. Kandidat archive/delete
> sebaiknya diputuskan terpisah setelah kebutuhan historis script tersebut
> dikonfirmasi.

---

# Prasyarat umum

## 1. Root backend

Jalankan command dari root repository backend:

```text
interactive-seismogram-viewer-backend/
├── app/
├── scripts/
├── alembic/
├── benchmark/
└── ...
```

## 2. Virtual environment

Aktifkan virtual environment atau gunakan executable Python langsung:

```powershell
.venv\Scripts\python.exe
```

## 3. `.env`

Isi `.env` sesuai kebutuhan backend.

Script yang memakai database membutuhkan konfigurasi database yang benar,
sedangkan script yang melakukan request FDSN membutuhkan konfigurasi endpoint
dan credential FDSN yang sesuai.

Konfigurasi backend utama dijelaskan di `README.md` root repository.

## 4. Data hardcode

Beberapa script menggunakan station/channel/tanggal hardcode, misalnya:

```text
IA.AAFM
2025-07-01
2026-09-03
```

Karena itu, hasil script tersebut bergantung pada ketersediaan data pada window
yang dipakai. Jangan menganggap `PASS` atau output tertentu sebagai jaminan
bahwa seluruh station, tanggal, atau kondisi lain memiliki perilaku yang sama.

---

# Catatan Maintenance Dokumentasi

Saat mengubah, mengganti nama, atau menghapus script di folder ini:

1. cari referensi nama file lama di seluruh repository;
2. perbarui command pada dokumentasi;
3. perbarui tabel status/fungsi di file ini;
4. periksa README dan dokumentasi terkait;
5. pastikan nama script yang ditulis benar-benar sama dengan file yang ada di
   repository.

Dokumentasi ini sengaja membedakan **script runtime**, **manual utility**,
**testing/experimental**, dan **possible legacy** agar script lama tidak
diasumsikan sebagai bagian dari execution flow aplikasi tanpa bukti pemanggilan.
