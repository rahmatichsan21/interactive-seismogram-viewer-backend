from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.stations import router as station_router
from app.routers.waveform import router as waveform_router
from app.routers.processing import router as processing_router
from app.routers.upload import router as upload_router
from app.routers.spectrogram import router as spectrogram_router
from app.routers.download import router as download_router

app = FastAPI(
    title="Interactive Seismogram Viewer API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(station_router)
app.include_router(waveform_router)
app.include_router(processing_router)
app.include_router(upload_router)
app.include_router(spectrogram_router)
app.include_router(download_router)


@app.on_event("startup")
async def startup_processing_cache_sweep():
    import asyncio

    from app.services.processing_cache import processing_cache

    async def sweep_loop():
        while True:
            await asyncio.sleep(60)
            removed = processing_cache.sweep()
            if removed:
                print(
                    f"[CACHE SWEEP] Removed {removed} "
                    f"expired entries"
                )

    asyncio.create_task(sweep_loop())


@app.on_event("startup")
async def startup_hourly_cache_cleanup():
    import asyncio
    from datetime import datetime, timedelta

    from app.core.config import HOURLY_CACHE_CLEAR_TIME
    from app.services.waveform_storage_service import (
        get_last_cleanup_date,
        run_waveform_cache_cleanup,
        set_last_cleanup_date,
    )

    clear_hour, clear_minute = map(
        int, HOURLY_CACHE_CLEAR_TIME.split(":")
    )

    def next_clear_time(from_time):
        """Waktu scheduled cleanup berikutnya setelah from_time."""
        candidate = from_time.replace(
            hour=clear_hour,
            minute=clear_minute,
            second=0,
            microsecond=0,
        )
        if candidate <= from_time:
            candidate += timedelta(days=1)
        return candidate

    async def cleanup_loop():
        while True:
            try:
                last_cleanup = get_last_cleanup_date()
                today_start = datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

                if (
                    last_cleanup is None
                    or last_cleanup < today_start
                ):
                    print(
                        "[CACHE CLEANUP] "
                        "Running missed daily cleanup"
                    )
                    deleted_files, deleted_rows = (
                        run_waveform_cache_cleanup()
                    )
                    set_last_cleanup_date()
                    print(
                        f"[CACHE CLEANUP] Removed "
                        f"{deleted_files} files"
                    )
                    print(
                        f"[CACHE CLEANUP] Removed "
                        f"{deleted_rows} database records"
                    )
                    print("[CACHE CLEANUP] Completed")
                else:
                    print(
                        "[CACHE CLEANUP] Daily cleanup "
                        "already done, skipping"
                    )

                # Hitung waktu menuju scheduled cleanup
                # berikutnya, bukan polling per detik.
                now = datetime.now()
                next_cleanup = next_clear_time(now)
                wait_seconds = (
                    next_cleanup - now
                ).total_seconds()

                print(
                    f"[CACHE CLEANUP] Next cleanup at "
                    f"{next_cleanup.strftime('%Y-%m-%d %H:%M')}"
                )
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(
                    f"[CACHE CLEANUP] Error: {exc} — "
                    "retry in 1 hour"
                )
                await asyncio.sleep(3600)

    asyncio.create_task(cleanup_loop())


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
