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

class InstrumentCorrectionOperation(BaseModel):
    """Remove instrument response dari waveform menjadi unit fisik."""

    type: Literal["instrument_correction"]

    # Unit output: Displacement (m), Velocity (m/s), Acceleration (m/s^2).
    output: Literal["DISP", "VEL", "ACC"] = "VEL"

    # Empat frekuensi corner untuk taper domain-frekuensi pengaman
    # response removal. Wajib memenuhi f1 < f2 < f3 < f4.
    # Default konservatif aman untuk channel dengan Nyquist >= 20 Hz
    # (sampling rate >= 40 Hz) — dapat diedit user per trace/channel.
    pre_filt: list[float] | None = None

    # Clipping inverse spectrum dalam dB (pengaman).
    water_level: float = 60

Operation = Annotated[
    Union[
        TrimOperation,
        FilterOperation,
        InstrumentCorrectionOperation,
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

    network: str | None = None
    station: str | None = None
    location: str
    channel: str
    sampling_rate: float

    # Unit hasil processing (hanya ada setelah Instrument Correction).
    output_unit: str | None = None
    unit_label: str | None = None

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