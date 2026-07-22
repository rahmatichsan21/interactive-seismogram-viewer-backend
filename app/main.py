from fastapi import FastAPI
from app.routers.stations import router as station_router
from app.routers.waveform import router as waveform_router
from app.routers import processing

app = FastAPI(
    title="Interactive Seismogram Viewer API",
    version="0.1.0",
)

app.include_router(station_router)
app.include_router(waveform_router)
app.include_router(processing.router)


@app.get("/")
def root():
    return {
        "message": "Interactive Seismogram Viewer API"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }