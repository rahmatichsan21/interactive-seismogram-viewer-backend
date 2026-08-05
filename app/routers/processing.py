from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.config import MAX_POINTS_PER_CHANNEL_LIMIT
from app.core.database import get_db
from app.models.processing import ProcessRequest
from app.services.processing_service import (
    process_waveform_per_channel,
)
from app.services.waveform_service import (
    trace_to_json,
    clamp_max_points,
    WaveformNoDataError,
)

from app.services.waveform_provider_service import (
    get_waveform,
)

from app.services.inventory_service import (
    estimate_max_points_per_channel,
    InventoryUnavailableError,
)

router = APIRouter(prefix="/process", tags=["Processing"])


@router.post("")
def process(
        request: ProcessRequest,
        db: Session = Depends(get_db),
    ):
    try:
        # Hard Limit - cek estimasi ukuran CHANNEL TERBESAR dari
        # metadata SEBELUM fetch waveform sungguhan dijalankan.
        # max(), bukan sum() lintas channel - sejak processing
        # jadi Sequential Per-Channel di bawah, puncak RAM
        # ditentukan channel terbesar yang sedang diproses saat
        # itu, bukan jumlah semua channel.
        estimated_max_points = estimate_max_points_per_channel(
            network=request.network,
            station=request.station,
            location=request.location,
            channel=request.channel,
            start_time=request.start_time,
            end_time=request.end_time,
        )

        if estimated_max_points > MAX_POINTS_PER_CHANNEL_LIMIT:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Channel terbesar pada request untuk "
                    f"{request.network}.{request.station}.."
                    f"{request.channel} diperkirakan "
                    f"menghasilkan "
                    f"{estimated_max_points:,} titik data "
                    f"mentah, melebihi batas "
                    f"{MAX_POINTS_PER_CHANNEL_LIMIT:,} per "
                    f"channel. Perkecil rentang waktu."
                ),
            )

        stream = get_waveform(
            db=db,
            network=request.network,
            station=request.station,
            location=request.location,
            channel=request.channel,
            start_time=request.start_time,
            end_time=request.end_time,
        )

        # max_points di-clamp SEKALI di sini (bukan di
        # trace_to_json) - jalur per-channel ini memanggil
        # trace_to_json() langsung (bukan lewat stream_to_json
        # yang biasanya melakukan clamp-nya sendiri), jadi
        # clamp-nya harus eksplisit di titik ini.
        max_points = clamp_max_points(request.max_points)

        response_traces = []

        # Sequential Per-Channel: process_waveform_per_channel()
        # adalah generator - tiap iterasi cuma SATU channel yang
        # "in flight" di memori. trace_to_json() (decimate +
        # serialize) dipanggil SEGERA per channel, sebelum
        # generator lanjut ke channel berikutnya dan melepas
        # referensi channel ini (lihat processing_service.py).
        for processed_trace in process_waveform_per_channel(
            stream=stream,
            operations=request.operations,
        ):
            response_traces.append(
                trace_to_json(processed_trace, max_points)
            )

        return {
            "station": request.station,
            "traces": response_traces,
        }

    except HTTPException:
        # Supaya HTTPException yang sengaja kita raise sendiri
        # di atas (413) tidak ikut tertangkap dan dibungkus ulang
        # jadi 500 oleh "except Exception" generik di bawah.
        raise

    except InventoryUnavailableError as exc:
        # Fail-closed: metadata channel tidak bisa diverifikasi
        # (BMKG timeout/error), request DITOLAK - bukan
        # dilewatkan begitu saja tanpa Hard Limit check.
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

    except WaveformNoDataError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except ValueError as exc:
        # Termasuk kegagalan validasi per-channel (mis. Nyquist
        # gagal di satu channel) - technical debt yang sudah kita
        # sepakati: kalau satu channel gagal, SELURUH request ini
        # gagal (all-or-nothing), belum partial-per-channel.
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )