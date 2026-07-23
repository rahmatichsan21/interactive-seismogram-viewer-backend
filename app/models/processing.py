from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TrimOperation(BaseModel):
    type: Literal["trim"]
    start_time: str
    end_time: str


Operation = Annotated[
    Union[
        TrimOperation,
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