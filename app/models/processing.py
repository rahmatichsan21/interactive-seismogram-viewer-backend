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

    # Opsional. Kalau diisi, trace dengan raw_point_count lebih
    # besar dari nilai ini akan di-decimate (Min-Max) di
    # stream_to_json(). None (default) = tidak ada decimation
    # sama sekali, perilaku identik dengan sebelum fitur ini ada.
    # Di-clamp (BUKAN ditolak/422) ke rentang [100, 20000] di
    # waveform_service._clamp_max_points() - lihat alasannya di
    # sana.
    max_points: int | None = None


class TraceResponse(BaseModel):
    """
    Kontrak "Fail Loud": `amplitude` HANYA muncul kalau
    `decimated=False`; `amplitude_min`/`amplitude_max` HANYA
    muncul kalau `decimated=True`. Field lain yang cuma relevan
    untuk salah satu kasus (decimation_method, decimation_factor,
    bucket_time_reference) mengikuti pola yang sama.

    Field-field ini defaultnya None BUKAN supaya boleh diabaikan
    - stream_to_json() SELALU mengisi field yang relevan untuk
    kasusnya, lalu men-dump dengan exclude_none=True supaya key
    yang tidak relevan benar-benar HILANG dari JSON (bukan cuma
    null), sesuai kesepakatan Fail Loud kita.
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