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