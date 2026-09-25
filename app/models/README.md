# `app/models`

Folder `app/models` mendefinisikan data model dan contract yang digunakan
backend.

Tanggung jawab folder ini terutama:

- model SQLAlchemy untuk persistence;
- schema Pydantic untuk request/response processing;
- schema request export.

## File

| File | Jenis | Tanggung jawab |
| --- | --- | --- |
| `waveform.py` | SQLAlchemy | Model `WaveformRecord` untuk raw waveform cache. |
| `processing.py` | Pydantic | Operation model, `ProcessRequest`, dan trace/process response contract. |
| `download.py` | Pydantic | Request model untuk MiniSEED export. |

---

## `waveform.py`

Model utama:

```text
WaveformRecord
```

Table:

```text
waveform_records
```

Field:

```text
id
network
station
location
channel
start_time
end_time
file_path
created_at
```

Cache identity dibatasi oleh unique constraint pada kombinasi:

```text
network
station
location
channel
start_time
end_time
```

Tujuannya mencegah dua row untuk cache window yang sama.

`file_path` menunjuk file MiniSEED yang menyimpan data waveform terkait.

---

## `processing.py`

### Operation types

Registry type operation saat ini:

```text
trim
filter
instrument_correction
```

### `TrimOperation`

Field:

```text
type = "trim"
start_time
end_time
```

### `FilterOperation`

`filter_type`:

```text
lowpass
highpass
bandpass
```

Parameter tersedia:

```text
freq
freqmin
freqmax
corners
zerophase
```

### `InstrumentCorrectionOperation`

Field utama:

```text
type = "instrument_correction"
output
pre_filt
water_level
```

`output`:

```text
DISP
VEL
ACC
```

Default `output` adalah `VEL`.

### `Operation`

`Operation` adalah discriminated union berdasarkan field:

```text
type
```

Operation baru harus ditambahkan ke union ini sebelum dapat diterima oleh
`ProcessRequest`.

---

## `ProcessRequest`

Field:

```text
network
station
location
channel
start_time
end_time
operations
max_points
session_id
```

`operations` menentukan pipeline processing.

`max_points` digunakan pada serialisasi waveform untuk menentukan apakah
temporal-order decimation diaktifkan.

`session_id` digunakan untuk local upload; tanpa `session_id`, processing
menggunakan waveform provider backend.

---

## Response Contract

### `TraceResponse`

Contract trace response mencakup:

```text
network
station
location
channel
sampling_rate
output_unit
unit_label
time
decimated
raw_point_count
requested_max_points
returned_point_count
amplitude
stats
```

Data waveform response selalu menggunakan:

```text
time[]
amplitude[]
```

### `ProcessResponse`

```text
station
traces[]
```

---

## `download.py`

### `DownloadTraceRequest`

Field:

```text
station
location
channel
```

Default `location`:

```text
*
```

### `MiniSeedDownloadRequest`

Memilih source:

```text
fdsn
local
```

Field utama meliputi:

```text
source
network
stations
location
channels
traces
start_time
end_time
trim_start
trim_end
session_id
```

Validasi source menggunakan pola:

```text
fdsn|local
```

---

## Ownership dan perubahan contract

`app/models/processing.py` adalah salah satu boundary contract frontend-backend.

Saat menambah operation:

1. tambahkan schema operation di `processing.py`;
2. tambahkan operation tersebut ke `Operation` union;
3. implementasikan handler di `app/processing/operations/`;
4. daftarkan handler di `app/processing/registry.py`;
5. pastikan router/service menyediakan context yang dibutuhkan.

Detail pipeline dimiliki `app/processing/README.md`, bukan folder models.
