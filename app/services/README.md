# `app/services`

Service berisi implementasi domain dan integrasi eksternal backend. Router
memanggil service; service tidak boleh bergantung pada komponen React.

| Area | File penting | Peran |
| --- | --- | --- |
| Waveform provider | `waveform_provider_service.py`, `waveform_storage_service.py` | Download FDSN, cache MySQL/MiniSEED, assembly window. |
| Serialisasi | `waveform_service.py` | Download helper dan serialisasi trace API. |
| Processing | `processing_service.py`, `processing_cache.py` | Processing per trace dan cache hasil final. |
| StationXML | `persistent_instrument_response_cache.py`, `response_cache.py`, `upload_storage.py` | Inventory FDSN dan inventory local session. |
| Analisis | `psd_service.py`, `hvsr_service.py`, `ttl_cache.py` | Perhitungan dan cache PSD/HVSR/spectrogram. |
| Export/data | `miniseed_export_service.py`, `inventory_service.py`, `station_service.py` | Export dan metadata station/channel. |

## Aturan identity trace

Identity trace terdiri dari network, station, location, dan channel. Service
yang membaca stream multi-station atau membangun cache harus memakai identity
aktual dari `trace.stats`, bukan station global dari request pertama.

## Cache dan storage

- Raw waveform disimpan dalam database dan file MiniSEED di `storage/waveforms`.
- Local upload berada di memory process dan terikat `session_id`.
- Hasil processing dan image analisis memakai cache RAM TTL/LRU.
- Cache berbeda memiliki lifecycle berbeda; jangan memakai cache processing
  untuk menggantikan raw waveform cache.
