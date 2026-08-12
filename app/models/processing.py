from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TrimOperation(BaseModel):
    type: Literal["trim"]
    start_time: str
    end_time: str

class FilterOperation(BaseModel):
    type: Literal["filter"]

    filter_type: Literal[
        "lowpass",
        "highpass",
        "bandpass",
    ]

    freq: float | None = None
    freqmin: float | None = None
    freqmax: float | None = None

    corners: int = 4
    zerophase: bool = True

Operation = Annotated[
    Union[
        TrimOperation,
        FilterOperation,
    ],
    Field(discriminator="type"),
]


class ProcessRequest(BaseModel):
    network: str
    station: str
    location: str
    channel: str
    start_time: str
    end_time: str

    operations: list[Operation] = []

    # Time Bucket decimation (temporal-order min/max).
    # Dipakai sebagai langkah PALING AKHIR setelah seluruh
    # operasi matematis berjalan di atas data mentah
    # (lihat waveform_service.trace_to_json).
    # Nilai = jumlah bucket yang ditargetkan (setiap bucket
    # menghasilkan hingga 2 titik output). None = tanpa
    # decimation.
    max_points: int | None = None

    # Optional: session_id untuk data dari Local File Viewer.
    # Jika diisi, backend mengambil waveform dari
    # upload_storage[ session_id ] alih-alih dari FDSN cache.
    session_id: str | None = None


class TraceResponse(BaseModel):
    """
    Kontrak response SATU trace.

    Time Bucket (temporal-order min/max decimation) diterapkan
    sebagai langkah terakhir serialisasi. Output SELALU memakai
    format `time[]` + `amplitude[]` — baik raw maupun decimated.
    Frontend tidak perlu membedakan mode rendering berdasarkan
    field `decimated`.
    """

    location: str
    channel: str
    sampling_rate: float

    time: list[str]

    decimated: bool
    raw_point_count: int
    requested_max_points: int | None = None
    returned_point_count: int

    amplitude: list[float]

    stats: dict | None = None


class ProcessResponse(BaseModel):
    station: str
    traces: list[TraceResponse]