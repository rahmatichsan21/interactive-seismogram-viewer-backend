# `app/routers`

Folder `app/routers` adalah HTTP boundary FastAPI. Router menerima request,
memvalidasi parameter melalui FastAPI/Pydantic, memanggil service, dan
menerjemahkan error menjadi HTTP response.

Business logic waveform/ObsPy yang berat berada di `app/services` atau
`app/processing`.

## Router yang didaftarkan

Semua router berikut didaftarkan oleh `app/main.py`:

| File | Prefix | Area |
| --- | --- | --- |
| `stations.py` | `/api` | Daftar dan informasi station |
| `waveform.py` | `/api` | Waveform, cache status, download source |
| `processing.py` | `/process` | Processing pipeline |
| `upload.py` | `/api/upload` | Local MiniSEED/StationXML session |
| `spectrogram.py` | `/api` | Spectrogram |
| `psd.py` | `/api` | PSD |
| `hvsr.py` | `/api` | HVSR |
| `download.py` | `/api/download` | MiniSEED/StationXML export |

---

## `stations.py`

Endpoints:

```text
GET /api/stations
GET /api/station-info
```

`/api/stations` membaca daftar station dari `data/stations.csv`.

`/api/station-info` menerima:

```text
network
station
```

dan mengambil location/channel metadata dari FDSN inventory service.

---

## `waveform.py`

Endpoints:

```text
GET /api/waveform
GET /api/waveform/status
POST /api/waveform/download
GET /api/channels
```

### `/api/waveform`

Parameter utama:

```text
network
station
location
channel
start_time
end_time
max_points
```

Backend mengambil waveform melalui `waveform_provider_service`.

Request dapat menggunakan channel wildcard seperti `SH*`; wildcard diexpand
berdasarkan FDSN inventory menjadi channel konkret.

`max_points` diteruskan ke serialisasi waveform.

### `/api/waveform/status`

Read-only completeness check terhadap cache untuk request waveform.

Response:

```json
{
  "download_needed": true
}
```

### `/api/waveform/download`

Memastikan window waveform yang diperlukan tersedia melalui provider dan
mengembalikan informasi apakah request melakukan download dari BMKG.

### `/api/channels`

Mengambil channel yang tersedia untuk:

```text
network
station
start_time
end_time
```

---

## `processing.py`

Endpoint:

```text
POST /process
```

Request menggunakan `ProcessRequest` dari `app/models/processing.py`.

Sumber waveform:

- FDSN/cache jika `session_id` tidak diisi;
- local upload session jika `session_id` diisi.

Processing menggunakan `process_waveform_per_channel()`.

`Instrument Correction` membutuhkan inventory/response:

- local upload → StationXML dari session;
- FDSN → response inventory yang di-resolve dan di-cache.

Response berisi:

```text
station
traces[]
```

Error utama yang diterjemahkan:

```text
404
400
500
```

sesuai kondisi no-data, invalid request, atau unexpected error.

---

## `upload.py`

Area:

```text
/api/upload
```

Endpoint utama:

```text
POST /api/upload/miniseed
POST /api/upload/stationxml
GET /api/upload/stationxml/{session_id}/validation
GET /api/upload/{session_id}/waveform
```

Local upload disimpan dalam process memory dan diikat oleh `session_id`.

Satu upload session dapat berisi:

- MiniSEED stream;
- beberapa StationXML inventory.

---

## `spectrogram.py`

Endpoint:

```text
GET /api/spectrogram
```

Sumber waveform dapat berupa:

- FDSN/backend waveform provider;
- local upload session.

Endpoint menggunakan raw full-resolution waveform dan menghasilkan PNG
base64.

Jika trace memiliki gap masked, rendering memproses segmen valid sehingga gap
tidak digambar sebagai data kontinu.

---

## `psd.py`

Endpoint:

```text
GET /api/psd
```

PSD menggunakan ObsPy `PPSD`.

Input dapat berasal dari:

- FDSN/cache;
- local upload.

Instrument response harus tersedia melalui:

- local StationXML;
- persistent/FDSN response resolution.

Output berupa PNG base64.

---

## `hvsr.py`

Endpoint:

```text
GET /api/hvsr
```

HVSR membutuhkan tiga channel:

```text
channel_n
channel_e
channel_z
```

Sumber waveform:

- FDSN/cache;
- local upload session.

Endpoint juga mendukung trim melalui:

```text
trim_start
trim_end
```

Output berisi image base64 dan metadata HVSR.

---

## `download.py`

Prefix:

```text
/api/download
```

Endpoint:

```text
POST /api/download/miniseed
GET /api/download/stationxml
```

MiniSEED export menggunakan `MiniSeedDownloadRequest`.

StationXML download menggunakan:

```text
network
station
```

---

## Trace identity

Untuk local upload multi-station, pemilihan trace harus mempertimbangkan
identity lengkap:

```text
network
station
location
channel
```

Memilih trace hanya berdasarkan `channel` tidak cukup ketika satu upload
session memuat beberapa station.

---

## Router → service relationship

Pola umum:

```text
HTTP
 ↓
router
 ↓
service/provider
 ↓
storage/cache/FDSN/processing
```

Router tidak seharusnya mengambil alih logic domain atau processing berat.

Untuk detail service:
[app/services/README.md](../services/README.md)

Untuk processing:
[app/processing/README.md](../processing/README.md)

Untuk request/response contract:
[app/models/README.md](../models/README.md)
