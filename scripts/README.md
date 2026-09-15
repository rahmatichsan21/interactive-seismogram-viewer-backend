# `scripts`

Folder ini berisi tools manual yang dijalankan langsung dengan
`python scripts/<nama_script>.py` — bukan bagian dari aplikasi FastAPI dan
tidak dijalankan otomatis. Dipakai untuk setup awal, maintenance cache/database,
diagnosa masalah lapangan, dan validasi manual perilaku backend (waveform,
cache, processing).

Semua script mengimpor modul dari `app/` (`app.core`, `app.models`,
`app.services`), sehingga harus dijalankan dari **root folder backend**
(folder yang berisi `app/`), dengan virtualenv aktif dan `.env` sudah terisi
sesuai `backend/README.md`.

```powershell
.venv\Scripts\python.exe scripts\<nama_script>.py
```

Beberapa script menerima argumen CLI (lihat kolom Cara pakai). Jalankan
`python scripts\<nama_script>.py --help` untuk melihat semua opsi jika
tersedia.

## Legenda risiko

- **READ-ONLY** — hanya membaca (DB, cache, atau FDSN); tidak mengubah state.
- **NETWORK** — melakukan request ke FDSN/BMKG (butuh `.env` valid dan koneksi).
- **LIVE DATABASE** — membaca dan/atau menulis ke MySQL yang dikonfigurasi di
  `DATABASE_URL` milik environment yang dipakai menjalankan script. Jangan
  jalankan terhadap database produksi tanpa memastikan targetnya benar.
- **DESTRUCTIVE** — dapat menghapus baris database dan/atau file cache
  (`storage/waveforms/*.mseed`) secara permanen. Backup atau pastikan
  environment sebelum menjalankan.

## ⚠️ Peringatan: script yang menghapus cache/database

Script berikut **menghapus data secara permanen** (baris `WaveformRecord`
di database dan/atau file `.mseed` di `storage/waveforms/`). Jangan
menjalankannya terhadap database yang dipakai orang lain atau environment
yang berisi data yang masih dibutuhkan, kecuali memang bertujuan mengosongkan
cache:

- `clear_all_cache.py` — hapus **seluruh** cache waveform (semua baris + semua
  file `.mseed`), tanpa konfirmasi.
- `cleanup_cache.py` — menjalankan rutin hourly cleanup yang sama seperti
  scheduler otomatis di `app/main.py` (hapus cache sesuai kebijakan retensi
  harian), secara manual/segera.
- `test_hourly_cache.py` — membersihkan cache di awal skrip sebagai bagian
  dari setup test, lalu menghapus lagi di beberapa titik pengujian.
- `test_seen_channels.py` — membersihkan cache di awal skrip (dan diulang di
  tengah skrip) sebagai bagian dari setup test.

## Setup

Dijalankan sekali di awal untuk menyiapkan database.

| Script | Fungsi | Risiko |
| --- | --- | --- |
| `create_tables.py` | Membuat semua tabel SQLAlchemy (`Base.metadata.create_all`) di database `DATABASE_URL`. | LIVE DATABASE |
| `check_database.py` | Cek koneksi MySQL berhasil dan menampilkan nama database yang terhubung. | READ-ONLY, LIVE DATABASE |

```powershell
.venv\Scripts\python.exe scripts\create_tables.py
.venv\Scripts\python.exe scripts\check_database.py
```

## Maintenance

Mengelola cache waveform yang tersimpan di database + `storage/waveforms/`.

| Script | Fungsi | Risiko |
| --- | --- | --- |
| `cleanup_cache.py` | Menjalankan `run_waveform_cache_cleanup()` (rutin cleanup harian yang sama dengan scheduler otomatis di `app/main.py`) secara manual, lalu mencatat waktu cleanup terakhir. | DESTRUCTIVE, LIVE DATABASE |
| `clear_all_cache.py` | Menghapus **semua** baris `WaveformRecord` dari database beserta seluruh file `.mseed` di `storage/waveforms/`, termasuk file yatim (orphaned) yang tidak lagi tercatat di database. | DESTRUCTIVE, LIVE DATABASE |

```powershell
.venv\Scripts\python.exe scripts\cleanup_cache.py
.venv\Scripts\python.exe scripts\clear_all_cache.py
```

## Diagnostic

Untuk menyelidiki state cache/database di lapangan, tanpa mengubah data
(kecuali disebutkan lain).

| Script | Fungsi | Risiko |
| --- | --- | --- |
| `diagnose_cache.py` | Menampilkan baris `WaveformRecord` yang cocok dengan satu window tetap (hardcode `IA.AAI`, 1 hari `2025-07-01`–`2025-07-02`) untuk inspeksi manual. | READ-ONLY, LIVE DATABASE |
| `diagnose_aafm_gap.py` | Memuat window cache lokal (`load_cached_window`) untuk satu rentang hardcode (`IA.AAFM`, channel `SH*`), lalu menampilkan detail per-trace (masked, finite/non-finite) dan gap sebelum/sesudah `merge()`. | READ-ONLY, LIVE DATABASE |
| `diagnose_fdsn_hourly.py` | Diagnosa per-jam untuk satu (network, station, channel, tanggal): mengecek apakah baris cache ada di DB dan apakah file MiniSEED-nya benar-benar ada di disk ("broken cache"). Opsi `--check-fdsn` menambahkan verifikasi langsung ke BMKG (read-only, hasil tidak disimpan) untuk jam yang cache-nya tidak lengkap. | READ-ONLY, LIVE DATABASE, NETWORK (hanya jika `--check-fdsn`) |

```powershell
.venv\Scripts\python.exe scripts\diagnose_cache.py
.venv\Scripts\python.exe scripts\diagnose_aafm_gap.py
.venv\Scripts\python.exe scripts\diagnose_fdsn_hourly.py --station AAFM --date 2026-09-08
.venv\Scripts\python.exe scripts\diagnose_fdsn_hourly.py --network IA --station AAFM --date 2026-09-08 --channels SHZ SHE SHN --check-fdsn
```

## Validation

Memverifikasi perilaku spesifik backend (decimation, processing pipeline,
wildcard channel) dengan skenario nyata via FDSN. Bukan bagian dari test
suite otomatis (tidak pakai `pytest`); dijalankan manual dan dibaca output
konsolnya (`PASS`/`assert`) oleh developer.

| Script | Fungsi | Risiko |
| --- | --- | --- |
| `verify_temporal.py` | Memverifikasi decimation temporal-order (di bawah dan di atas `MAX_DISPLAY_POINTS`) memakai waveform FDSN `IA.AAFM`. | NETWORK |
| `smoke_test_processing.py` | Smoke test operation `trim` melalui `apply_pipeline` terhadap waveform FDSN `IA.AAFM`, menampilkan stream sebelum/sesudah. | NETWORK |

```powershell
.venv\Scripts\python.exe scripts\verify_temporal.py
.venv\Scripts\python.exe scripts\smoke_test_processing.py
```

## Experimental / legacy (bukan regression test resmi)

Script berikut ditulis untuk memvalidasi fitur tertentu pada satu titik waktu
pengembangan (nama file menyebut versi/skema cache spesifik, mis. "v2",
"hourly", "seen channels"). Isinya masih bisa dijalankan dan berguna sebagai
referensi/regresi manual, tetapi **bukan test suite resmi** — tidak dijalankan
di CI, tidak dijaga sinkron otomatis dengan perubahan kode, dan sebagian
berisi assert yang mengasumsikan state data FDSN tertentu (mis. window waktu
hardcode) yang bisa saja sudah tidak valid. Jangan memperlakukan hasil
`PASS`/`FAIL` script ini sebagai jaminan status build.

| Script | Fungsi | Risiko |
| --- | --- | --- |
| `test_hourly_cache.py` | Skenario manual hourly cache (window exact, cleanup, dsb.) terhadap `IA.AAFM`. | DESTRUCTIVE, NETWORK, LIVE DATABASE |
| `test_processing_cache.py` | Skenario manual `ProcessingCache` (L1 cache hasil processing) versi awal. | NETWORK, LIVE DATABASE |
| `test_processing_cache_v2.py` | Skenario manual `ProcessingCache` varian "Hybrid A+D"; superseding/varian dari `test_processing_cache.py`. | NETWORK, LIVE DATABASE |
| `test_seen_channels.py` | Skenario manual `get_seen_channels()` sebagai source of truth wildcard channel; membersihkan cache di beberapa titik sebagai bagian setup. | DESTRUCTIVE, NETWORK, LIVE DATABASE |
| `test_obspy_aafm_gap_processing.py` | Eksperimen langsung memakai `obspy.clients.fdsn.Client` (bukan lewat service backend) untuk menyelidiki gap pada `IA.AAFM`. | NETWORK |
| `visual_compare.py` | Membandingkan waveform hasil decimation vs raw secara visual; menyimpan gambar `visual_compare.png` ke root backend memakai `matplotlib`. | NETWORK (menulis file gambar di root backend) |
| `generate_station_csv.py` | Meng-generate ulang `data/stations.csv` dengan memvalidasi kredensial FDSN per stasiun (`get_waveforms` 1 detik) terhadap seluruh inventory BMKG network `IA`. Menimpa `data/stations.csv` — pertimbangkan backup (`data/stations_backup.csv`) sebelum menjalankan. | NETWORK, menimpa file `data/stations.csv` |

```powershell
.venv\Scripts\python.exe scripts\test_hourly_cache.py
.venv\Scripts\python.exe scripts\test_processing_cache.py
.venv\Scripts\python.exe scripts\test_processing_cache_v2.py
.venv\Scripts\python.exe scripts\test_seen_channels.py
.venv\Scripts\python.exe scripts\test_obspy_aafm_gap_processing.py
.venv\Scripts\python.exe scripts\visual_compare.py
.venv\Scripts\python.exe scripts\generate_station_csv.py
```

## Prasyarat umum

- Dijalankan dari root backend dengan virtualenv aktif (`app/` harus bisa
  di-import).
- `.env` terisi sesuai `backend/README.md` (`DATABASE_URL`, `BMKG_URL`,
  `BMKG_USERNAME`, `BMKG_PASSWORD`, dst.) untuk script yang menandai
  **LIVE DATABASE** atau **NETWORK**.
- Beberapa script memakai data waveform hardcode dari station/tanggal
  tertentu (mis. `IA.AAFM`, `2025-07-01`); hasilnya hanya valid selama data
  itu masih tersedia di FDSN/cache. Sesuaikan konstanta di script bila data
  tersebut sudah tidak ada.
- `visual_compare.py` membutuhkan `matplotlib` (lihat `requirements.txt`).