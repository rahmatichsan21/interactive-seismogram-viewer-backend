# `app/models`

Folder ini mendefinisikan contract data backend.

| File | Tanggung jawab |
| --- | --- |
| `waveform.py` | Model SQLAlchemy record raw waveform cache. |
| `processing.py` | Pydantic request/response processing dan union operation. |
| `download.py` | Model request export MiniSEED. |

`processing.py` adalah batas contract frontend-backend. Metadata UI seperti
`id`, `enabled`, dan bentuk `params` adalah milik frontend; adapter frontend
mengubahnya menjadi operation backend sebelum `POST /process`.

Saat menambah operation, tambah schema pada union di sini, handler pada
`app/processing/operations/`, dan registry operation.
