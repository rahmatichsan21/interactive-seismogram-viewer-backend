# `app/processing`

Folder `app/processing` mengimplementasikan pipeline operasi waveform berbasis
ObsPy.

Pipeline bertanggung jawab menerapkan operation dalam urutan request.
`processing_service.py` mengatur per-trace handling, gap handling, context, dan
ProcessingCache.

## Struktur

```text
app/processing/
├── README.md
├── registry.py
├── pipeline.py
└── operations/
    ├── trim.py
    ├── filter.py
    └── instrument_correction.py
```

---

## Registry

`registry.py` memetakan operation type ke handler:

```text
trim → apply_trim
filter → apply_filter
instrument_correction → apply_instrument_correction
```

Jika operation baru dibuat, operation tersebut harus:

1. memiliki schema pada `app/models/processing.py`;
2. memiliki handler pada `operations/`;
3. ditambahkan ke `OPERATION_REGISTRY`.

---

## Pipeline

`pipeline.py` menjalankan operation secara berurutan:

```text
input stream
    ↓
operation 1
    ↓
operation 2
    ↓
operation 3
    ↓
output stream
```

Handler dipanggil berdasarkan:

```text
operation.type
```

Pipeline tidak mengelola cache hasil final. Itu dilakukan di
`processing_service.py`.

---

## Gap handling

Trace dengan gap dapat menjadi masked trace.

`processing_service.py` memastikan gap dipisahkan sebelum operation yang tidak
aman dijalankan langsung terhadap masked data.

Alur utama:

```text
masked trace
    ↓
split()
    ↓
process tiap segmen valid
    ↓
merge(fill_value=0)
```

Gap tidak diisi nol sebelum filter/instrument correction.

Setelah processing, hasil dapat menjadi stream kontinu dengan nilai pengisi pada
lokasi gap sesuai workflow service.

---

## `trim`

File:

```text
operations/trim.py
```

Operation:

```text
type = "trim"
start_time
end_time
```

`end_time` harus lebih besar daripada `start_time`.

Handler bekerja pada copy stream dan menggunakan ObsPy `Stream.trim()`.

---

## `filter`

File:

```text
operations/filter.py
```

Jenis:

```text
lowpass
highpass
bandpass
```

Parameter filter bergantung pada jenis operation:

### Lowpass / Highpass

Menggunakan:

```text
freq
corners
zerophase
```

### Bandpass

Menggunakan:

```text
freqmin
freqmax
corners
zerophase
```

Handler memvalidasi frekuensi terhadap Nyquist.

Untuk lowpass/highpass:

```text
freq < Nyquist
```

Untuk bandpass:

```text
freqmax < Nyquist
```

Jika tidak memenuhi, handler melempar `ValueError`.

---

## `instrument_correction`

File:

```text
operations/instrument_correction.py
```

Operation menggunakan `Trace.remove_response()`.

Output unit:

```text
DISP
VEL
ACC
```

Mapping unit frontend:

```text
DISP → m
VEL  → m/s
ACC  → m/s²
```

### Response requirement

Handler membutuhkan:

```text
context["inventory"]
```

Response dicari menggunakan:

```text
trace.id
trace.stats.starttime
```

sehingga matching mencakup network, station, location, channel, dan waktu.

### `pre_filt`

Jika diberikan:

```text
[f1, f2, f3, f4]
```

wajib memenuhi:

```text
f1 < f2 < f3 < f4
```

`f4` juga harus lebih kecil daripada Nyquist trace.

### `water_level`

`water_level` tidak boleh negatif.

Default model saat ini:

```text
60
```

### Correction options

Handler menjalankan:

```text
zero_mean=True
taper=True
taper_fraction=0.05
plot=False
```

---

## Processing order

Urutan operation mengikuti urutan list pada request.

Contoh:

```text
trim
→ filter
→ instrument_correction
```

Jika operation diubah urutannya, backend menerapkannya sesuai urutan baru
karena operation bersifat sequential.

---

## Service boundary

`app/processing` tidak mengambil data FDSN secara langsung.

Context dan stream diberikan oleh processing service/router.

```text
router
  ↓
processing_service
  ↓
processing pipeline
  ↓
operation handlers
```

Detail request/response contract:
[app/models/README.md](../models/README.md)

Detail service/cache:
[app/services/README.md](../services/README.md)

---

## Menambah operation

Checklist repository:

1. Tambahkan model operation di `app/models/processing.py`.
2. Masukkan model ke union `Operation`.
3. Buat handler baru di `app/processing/operations/`.
4. Daftarkan handler di `registry.py`.
5. Pastikan `processing_service.py` menyediakan context yang diperlukan.
6. Pastikan router menerima dan meneruskan request yang sesuai.
7. Jika operation diekspos ke frontend, tambahkan mapping pada frontend.
8. Tambahkan validasi/testing manual atau automated test yang sesuai.
