from pydantic import BaseModel, Field


class DownloadTraceRequest(BaseModel):
    station: str
    location: str = "*"
    channel: str


class MiniSeedDownloadRequest(BaseModel):
    source: str = Field(pattern="^(fdsn|local)$")
    network: str | None = None
    stations: list[str] = []
    location: str = "*"
    channels: list[str] = []
    traces: list[DownloadTraceRequest] = []
    start_time: str | None = None
    end_time: str | None = None
    trim_start: str | None = None
    trim_end: str | None = None
    session_id: str | None = None
