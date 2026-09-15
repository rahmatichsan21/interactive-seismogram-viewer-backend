# `app/routers`

Router adalah boundary HTTP FastAPI. Ia menerima parameter request, memanggil
service, dan menerjemahkan error ke response API. Logic waveform/ObsPy yang
berat tetap berada di `app/services/` atau `app/processing/`.

| Router | Area API |
| --- | --- |
| `stations.py` | daftar dan metadata station |
| `waveform.py` | waveform FDSN, status cache, download source |
| `processing.py` | pipeline processing via `POST /process` |
| `upload.py` | MiniSEED/StationXML local session dan validasi inventory |
| `spectrogram.py` | image spectrogram per trace |
| `psd.py` | image PSD per trace |
| `hvsr.py` | analisis HVSR per family N/E/Z |
| `download.py` | export MiniSEED dan StationXML |

Untuk local upload, router analisis harus menyaring trace memakai identity
lengkap: network, station, location, dan channel. Jangan memilih trace pertama
berdasarkan channel saja karena satu session dapat memuat beberapa station.

Router didaftarkan di `app/main.py`; CORS dan exception handler global juga
berada di sana.
