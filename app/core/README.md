# `app/core`

Folder ini berisi dependency infrastruktur bersama; bukan business logic
waveform atau operation processing.

| File | Tanggung jawab |
| --- | --- |
| `config.py` | Membaca `.env`, path aplikasi, dan parameter runtime/cache. |
| `database.py` | Engine SQLAlchemy, session dependency, dan base model. |
| `fdsn_client.py` | Client ObsPy untuk BMKG FDSN. |
| `logging_config.py` | Konfigurasi logging backend. |

## Hal penting

- Konfigurasi wajib tidak boleh memiliki fallback diam-diam.
- `BASE_DIR` adalah root backend dan dipakai untuk path data/storage.
- Kredensial FDSN berasal dari `.env`; jangan ditulis ke source atau log.
