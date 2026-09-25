# `app/core`

Folder `app/core` berisi dependency infrastruktur bersama yang digunakan oleh
bagian lain dari backend. Folder ini bukan tempat business logic waveform atau
operation processing.

## File

| File | Tanggung jawab |
| --- | --- |
| `config.py` | Membaca environment, menentukan path repository, dan menyediakan parameter runtime/cache. |
| `database.py` | SQLAlchemy engine, session factory, dan dependency `get_db()`. |
| `fdsn_client.py` | Membuat client ObsPy FDSN/BMKG. |
| `logging_config.py` | Menyiapkan konfigurasi logging backend. |

---

## Configuration

`config.py` menjalankan `load_dotenv()` dan menggunakan root repository sebagai
`BASE_DIR`.

Path penting:

```text
BASE_DIR
├── data/
│   └── stations.csv
└── storage/
```

`STATION_CSV` ditentukan sebagai:

```text
BASE_DIR / "data" / "stations.csv"
```

### Required environment

`config.py` membaca:

```text
BMKG_URL
BMKG_USERNAME
BMKG_PASSWORD
MAX_DISPLAY_POINTS
CACHE_WINDOW_SECONDS
HOURLY_CACHE_CLEAR_TIME
```

`database.py` membaca:

```text
DATABASE_URL
```

Credential FDSN berasal dari `.env` dan tidak boleh ditulis ke source code atau
log.

### Defaulted environment

`config.py` menyediakan default untuk variable operasional seperti:

```text
FDSN_TIMEOUT_SECONDS
MAX_DOWNLOAD_ATTEMPTS
RETRY_DELAY_SECONDS
PROCESSING_CACHE_TTL_SECONDS
PROCESSING_CACHE_MAX_ENTRIES
PROCESSING_CACHE_MAX_SIZE_BYTES
RESPONSE_CACHE_TTL_SECONDS
RESPONSE_CACHE_MAX_ENTRIES
PROCESSING_SWEEP_INTERVAL_SECONDS
CACHE_CLEANUP_RETRY_SECONDS
PPSD_LENGTH_SECONDS
PPSD_OVERLAP
PSD_CACHE_TTL_SECONDS
PSD_CACHE_MAX_ENTRIES
SPECTROGRAM_CACHE_TTL_SECONDS
SPECTROGRAM_CACHE_MAX_ENTRIES
GAP_THRESHOLD_PERCENT
HVSR_WINDOW_SECONDS
HVSR_FMIN
HVSR_FMAX
HVSR_REJECTION_ENABLED
HVSR_CACHE_TTL_SECONDS
HVSR_CACHE_MAX_ENTRIES
```

### Validation

`HOURLY_CACHE_CLEAR_TIME` harus berformat dua digit:

```text
HH:MM
```

dengan rentang:

```text
00:00
```

hingga:

```text
23:59
```

`GAP_THRESHOLD_PERCENT` harus berada pada rentang `0` sampai `100`.

`MAX_DISPLAY_POINTS` dan `CACHE_WINDOW_SECONDS` harus dapat dikonversi menjadi
integer karena keduanya langsung diparse saat configuration module dimuat.

---

## Database

`database.py` membuat:

- SQLAlchemy engine menggunakan `DATABASE_URL`;
- `SessionLocal`;
- `Base`;
- dependency generator `get_db()`.

`DATABASE_URL` wajib ada. Tanpa variable tersebut, import database akan
melempar `ValueError`.

Schema versioning ditangani Alembic di luar `app/core`. `alembic/env.py`
mengimpor `Base` dan `DATABASE_URL` dari module ini.

---

## FDSN Client

`fdsn_client.py` membuat satu ObsPy `Client` menggunakan:

```text
BMKG_URL
BMKG_USERNAME
BMKG_PASSWORD
FDSN_TIMEOUT_SECONDS
```

Client tersebut digunakan oleh service dan utility yang perlu mengakses FDSN
BMKG.

---

## Logging

`logging_config.py` dipanggil saat startup melalui `app/main.py`.

Logging dipakai oleh router/service untuk diagnostik runtime. Credential FDSN
harus tetap berasal dari environment dan tidak dicatat ke log.

---

## Dependency Relationship

Secara umum:

```text
app/core/config.py
        ↓
database.py / fdsn_client.py
        ↓
models / services
        ↓
routers / application
```

`app/core` sebaiknya tetap berisi infrastructure/shared configuration dan tidak
menyerap business logic dari `services` atau operation processing.
