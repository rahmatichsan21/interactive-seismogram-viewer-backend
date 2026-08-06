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

    # Time Bucket decimation (min/max). Dipakai sebagai langkah
    # PALING AKHIR setelah seluruh operasi matematis berjalan di
    # atas data mentah (lihat waveform_service.trace_to_json).
    # Default 2000 titik per trace; None = tanpa decimation.
    max_points: int | None = 2000


class TraceResponse(BaseModel):
    """
    Kontrak response SATU trace. Decimation (kalau aktif) hanya
    diterapkan sebagai langkah terakhir: `amplitude_min`/
    `amplitude_max` muncul kalau `decimated=True`, `amplitude`
    muncul kalau `decimated=False`. Field yang tidak relevan
    di-drop lewat exclude_none=True, bukan dijadikan null.
    """

    location: str
    channel: str
    sampling_rate: float

    time: list[str]

    decimated: bool
    raw_point_count: int
    requested_max_points: int | None = None
    returned_point_count: int

    # Hanya ada kalau decimated=False.
    amplitude: list[float] | None = None

    # Hanya ada kalau decimated=True.
    amplitude_min: list[float] | None = None
    amplitude_max: list[float] | None = None
    decimation_method: str | None = None
    decimation_factor: int | None = None
    bucket_time_reference: str | None = None

    stats: dict | None = None


class ProcessResponse(BaseModel):
    station: str
    traces: list[TraceResponse]