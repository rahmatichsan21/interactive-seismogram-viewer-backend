import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.logging_config import setup_logging
from app.routers.stations import router as station_router
from app.routers.waveform import router as waveform_router
from app.routers.processing import router as processing_router
from app.routers.upload import router as upload_router
from app.routers.spectrogram import router as spectrogram_router
from app.routers.download import router as download_router
from app.routers.psd import router as psd_router
from app.routers.hvsr import router as hvsr_router

setup_logging()

logger = logging.getLogger(__name__)

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
app.include_router(psd_router)
app.include_router(hvsr_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log exception tak terduga (500) + kembalikan error ke frontend."""
    logger.exception(
        "Unhandled error %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.on_event("startup")
async def startup_processing_cache_sweep():
    import asyncio

    from app.core.config import PROCESSING_SWEEP_INTERVAL_SECONDS
    from app.services.processing_cache import processing_cache
    from app.services.ttl_cache import (
        psd_cache,
        spectrogram_cache,
        hvsr_cache,
    )

    async def sweep_loop():
        while True:
            await asyncio.sleep(PROCESSING_SWEEP_INTERVAL_SECONDS)
            removed = processing_cache.sweep()
            if removed:
                logger.info(
                    "[CACHE SWEEP] Removed %d expired entries",
                    removed,
                )
            removed_psd = psd_cache.sweep()
            removed_spec = spectrogram_cache.sweep()
            removed_hvsr = hvsr_cache.sweep()
            if removed_psd or removed_spec or removed_hvsr:
                logger.info(
                    "[CACHE SWEEP] Removed PSD=%d spectrogram=%d "
                    "hvsr=%d",
                    removed_psd,
                    removed_spec,
                    removed_hvsr,
                )

    asyncio.create_task(sweep_loop())


@app.on_event("startup")
async def startup_hourly_cache_cleanup():
    import asyncio
    from datetime import datetime, timedelta

    from app.core.config import HOURLY_CACHE_CLEAR_TIME
    from app.core.config import CACHE_CLEANUP_RETRY_SECONDS
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
                    logger.info(
                        "[CACHE CLEANUP] Running missed daily cleanup"
                    )
                    deleted_files, deleted_rows = (
                        run_waveform_cache_cleanup()
                    )
                    set_last_cleanup_date()
                    logger.info(
                        "[CACHE CLEANUP] Removed %d files",
                        deleted_files,
                    )
                    logger.info(
                        "[CACHE CLEANUP] Removed %d database records",
                        deleted_rows,
                    )
                    logger.info("[CACHE CLEANUP] Completed")
                else:
                    logger.info(
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

                logger.info(
                    "[CACHE CLEANUP] Next cleanup at %s",
                    next_cleanup.strftime("%Y-%m-%d %H:%M"),
                )
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[CACHE CLEANUP] Error — retry in 1 hour"
                )
                await asyncio.sleep(CACHE_CLEANUP_RETRY_SECONDS)

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
