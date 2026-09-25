# `app/services`

Folder `app/services` berisi domain logic, integrasi eksternal, storage, cache,
analysis, dan helper yang dipakai oleh router.

Router sebaiknya bertindak sebagai HTTP boundary; service menangani logic
aplikasi dan interaksi dengan FDSN, database, filesystem, ObsPy, serta analysis
engine.

## Service map

| Area | File | Peran |
| --- | --- | --- |
| Waveform provider | `waveform_provider_service.py` | Resolve cache/download, wildcard expansion, assembly waveform |
| Waveform storage | `waveform_storage_service.py` | Cache window MySQL + MiniSEED, load/save, cleanup |
| Waveform serialization | `waveform_service.py` | FDSN download helper dan JSON serialization/decimation |
| Processing | `processing_service.py`, `processing_cache.py` | Processing per channel dan ProcessingCache |
| StationXML response | `persistent_instrument_response_cache.py`, `response_cache.py` | L1/L2 instrument response cache dan FDSN fetch |
| Upload | `upload_storage.py` | In-process local MiniSEED/StationXML sessions |
| Inventory | `inventory_service.py` | FDSN inventory and channel/location helpers |
| Station | `station_service.py` | Station CSV dan station metadata |
| PSD | `psd_service.py` | ObsPy PPSD image generation |
| HVSR | `hvsr_service.py` | hvsrpy processing and image generation |
| Generic image cache | `ttl_cache.py` | RAM TTL/LRU cache PSD/Spectrogram/HVSR |
| Export | `miniseed_export_service.py` | MiniSEED selection, trim, and export |

---

## Waveform provider

`waveform_provider_service.py` adalah jalur utama pengambilan waveform.

Secara konseptual:

```text
request
  ↓
hourly UTC-aligned windows
  ↓
cache completeness check
  ├── complete → load cache
  └── incomplete → download missing windows
  ↓
assemble
  ↓
preserve gaps
  ↓
trim to requested range
```

### Wildcard channel

Wildcard seperti:

```text
*
SH*
S*
```

tidak disimpan sebagai channel literal di cache.

Provider mengambil inventory FDSN level `channel`, melakukan expansion ke channel
konkret, lalu memproses channel tersebut satu per satu.

---

## Raw waveform cache

`waveform_storage_service.py` menyimpan setiap trace dalam window cache sebagai:

- row `WaveformRecord`;
- file MiniSEED.

Lokasi file:

```text
storage/waveforms/
```

File cache memakai identity:

```text
network
station
location
channel
window_start
window_end
```

### Cache lookup

Load cache menggunakan wildcard-aware lookup untuk location dan channel.

Cache completeness dicek per channel dan per window.

### Cleanup

`run_waveform_cache_cleanup()`:

- menghapus seluruh file waveform cache;
- menghapus persistent response StationXML;
- menghapus semua `WaveformRecord`;
- mengembalikan jumlah file/row yang dihapus.

Cleanup dijadwalkan oleh `app/main.py` berdasarkan
`HOURLY_CACHE_CLEAR_TIME`.

Marker tanggal cleanup:

```text
storage/.last_cleanup
```

---

## Waveform serialization

`waveform_service.py` melakukan:

- FDSN download;
- retry untuk error transient;
- transform trace menjadi JSON;
- temporal-order decimation.

Retry menggunakan:

```text
MAX_DOWNLOAD_ATTEMPTS
RETRY_DELAY_SECONDS
```

### Temporal-order decimation

Decimation dilakukan pada tahap serialisasi, setelah processing.

Trigger:

```text
raw_point_count > MAX_DISPLAY_POINTS
```

Jika `max_points` tidak diberikan, endpoint dapat mengirim data tanpa decimation.

Output trace selalu menggunakan:

```text
time[]
amplitude[]
```

Gap masked pada trace direpresentasikan pada tahap serialisasi tanpa membuat
timestamp `NaN`.

---

## Processing service

`processing_service.py` mengatur pipeline processing per channel/trace dan
context seperti inventory.

Dengan operasi `Instrument Correction`, inventory di-resolve terlebih dahulu.

ProcessingCache digunakan untuk hasil processing final/prefix sesuai logic
service.

Detail operation pipeline:
[app/processing/README.md](../processing/README.md)

---

## ProcessingCache

`processing_cache.py` adalah cache in-memory untuk hasil processing.

Karakteristik:

- TTL;
- LRU/max entries;
- max size;
- hilang ketika process backend restart.

Parameter utama:

```text
PROCESSING_CACHE_TTL_SECONDS
PROCESSING_CACHE_MAX_ENTRIES
PROCESSING_CACHE_MAX_SIZE_BYTES
```

---

## StationXML dan instrument response

Ada dua level response cache:

### L1

`response_cache.py`

```text
RAM
TTL/LRU
key = (network, station)
```

### L2

`persistent_instrument_response_cache.py`

```text
storage/responses/
```

Response persistent disimpan sebagai StationXML.

### Resolve order

Secara konsep:

```text
L1 RAM
  ↓ miss
L2 persistent StationXML
  ↓ miss
FDSN/BMKG
```

`resolve_instrument_response()` juga menggunakan single-flight agar request
concurrent untuk station yang sama tidak melakukan fetch FDSN ganda.

Untuk local upload, `upload_storage.py` menyimpan satu atau beberapa
StationXML dalam session dan dapat menggabungkannya kembali menjadi satu
inventory.

Response dicocokkan oleh ObsPy berdasarkan:

```text
network
station
location
channel
time
```

---

## Upload storage

`upload_storage.py` menggunakan dictionary in-process yang keyed by
`session_id`.

Session dapat menyimpan:

```text
stream
stationxml_inventories
```

Storage ini:

- bukan database;
- bukan raw FDSN cache;
- hilang ketika process backend restart.

---

## Inventory dan station services

`inventory_service.py` menyediakan helper untuk:

- mengambil FDSN inventory;
- iterate network/station/channel;
- unique channel;
- unique location;
- channel availability.

`station_service.py`:

- membaca `data/stations.csv`;
- mengembalikan list station;
- mengambil station info dari inventory;
- masih memiliki helper untuk generate ulang station CSV dari inventory FDSN.

Utility resmi untuk penambahan station yang tidak melakukan regenerate seluruh
CSV berada di `scripts/add_station_csv.py`.

---

## PSD

`psd_service.py` menggunakan ObsPy `PPSD`.

Parameter utama:

```text
PPSD_LENGTH_SECONDS
PPSD_OVERLAP
```

PSD membutuhkan instrument response Inventory.

Waveform yang lebih pendek dari `ppsd_length` ditolak.

PPSD menggunakan `skip_on_gaps=True` agar segmen yang beririsan dengan gap
tidak diproses sebagai data nol.

Output image dikembalikan sebagai PNG base64.

---

## Spectrogram

Spectrogram diimplementasikan pada router `spectrogram.py` dengan helper/cache
service yang tersedia.

Untuk trace bergap, rendering membagi trace menjadi segmen valid sehingga gap
tidak menjadi area energi palsu pada spectrogram.

Hasil image menggunakan RAM TTL cache.

---

## HVSR

`hvsr_service.py` menggunakan `hvsrpy`.

Input adalah tiga komponen:

```text
N
E
Z
```

Validasi internal mencakup:

- trace tersedia;
- data tidak kosong;
- tidak ada NaN/Inf;
- tidak flat;
- sampling rate cocok;
- timestamp selaras;
- durasi kompatibel;
- durasi cukup untuk `HVSR_WINDOW_SECONDS`.

Parameter configurable:

```text
HVSR_WINDOW_SECONDS
HVSR_FMIN
HVSR_FMAX
HVSR_REJECTION_ENABLED
```

Hasil menggunakan RAM TTL cache.

Peak search pada implementation saat ini menggunakan eksperimen bounded
`fp/2` sampai `2*fp`. Ini adalah behavior implementation saat ini, bukan
klaim bahwa rentang tersebut merupakan rule resmi Geopsy/SESAME.

---

## Generic analysis cache

`ttl_cache.py` menyediakan cache generic in-memory dengan:

- TTL;
- LRU eviction;
- lazy expiry;
- explicit sweep.

Singleton cache digunakan untuk:

```text
psd_cache
spectrogram_cache
hvsr_cache
```

Parameter berasal dari `app/core/config.py`.

---

## MiniSEED export

`miniseed_export_service.py` menangani:

- source `local` atau `fdsn`;
- pemilihan trace;
- export trim;
- penulisan MiniSEED;
- filename generation.

Untuk gappy stream, export melakukan `split()` terlebih dahulu karena writer
MiniSEED tidak menerima masked array.

---

## Trace identity

Service yang bekerja pada stream multi-station harus menggunakan identity aktual
trace:

```text
network
station
location
channel
```

Jangan mengandalkan station global request ketika stream mengandung beberapa
station.

---

## Relationship

Pola utama:

```text
Router
  ↓
Service
  ├── Core / DB
  ├── FDSN
  ├── Cache
  ├── Storage
  ├── ObsPy
  └── Analysis engine
```

Service tidak boleh bergantung pada komponen React/frontend.
