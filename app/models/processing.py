from typing import Literal

from pydantic import BaseModel


class TrimOperation(BaseModel):
    type: Literal["trim"]
    start_time: str
    end_time: str


class ProcessRequest(BaseModel):
    network: str
    station: str
    location: str
    channel: str
    start_time: str
    end_time: str

    operations: list[TrimOperation] = []