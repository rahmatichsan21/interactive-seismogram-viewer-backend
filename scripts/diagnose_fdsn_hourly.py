"""
scripts/diagnose_fdsn_hourly.py — Diagnostic PER-JAM untuk SATU
(network, station, channel-channel, tanggal) yang window 24-jamnya
tidak kunjung fully cached di benchmark/fdsn_cache_benchmark.py.

Script BARU, TERPISAH dari benchmark (ram_cpu_benchmark.py dan
fdsn_cache_benchmark.py TIDAK disentuh sama sekali) — murni untuk
menjawab pertanyaan diagnostic:
  - Jam mana (dari 24 window UTC-aligned selebar CACHE_WINDOW_SECONDS)
    yang row cache-nya BENAR-BENAR ada di DB (WaveformRecord)?
  - Kalau row ada, apakah file MiniSEED-nya BENAR-BENAR ada di disk
    (bisa saja row ada tapi file hilang — "broken cache")?
  - (Opsional, --check-fdsn) Untuk jam yang cache-nya tidak lengkap,
    apakah BMKG (FDSN) memang TIDAK PUNYA data pada jam itu (artinya
    window itu SECARA PERMANEN tidak akan pernah fully cached, wajar),
    atau BMKG sebenarnya PUNYA data tapi gagal ter-download/tersimpan
    (indikasi bug di alur download/save)?

TIDAK mengubah kode aplikasi apapun — hanya membaca (SELECT) dari DB
lewat model yang sudah ada (app.models.waveform.WaveformRecord), dan
opsional membaca langsung dari BMKG lewat client FDSN yang sudah ada
(app.core.fdsn_client.client) — read-only, hasil --check-fdsn TIDAK
disimpan ke cache/DB.

Cara pakai (jalankan dari ROOT project, venv aktif, .env sudah ada —
sama seperti scripts/diagnose_cache.py yang sudah ada):

  # Cek per-jam murni dari DB (cepat, tanpa panggil BMKG):
  python scripts/diagnose_fdsn_hourly.py --station AAFM --date 2026-09-08

  # + verifikasi ke BMKG langsung untuk jam yang cache-nya bolong
  # (lebih lambat, satu request FDSN per jam yang bermasalah):
  python scripts/diagnose_fdsn_hourly.py --station AAFM --date 2026-09-08 \
      --channels SHZ SHE SHN --check-fdsn

  # Station/tanggal lain, channel custom:
  python scripts/diagnose_fdsn_hourly.py --network IA --station AAI \
      --date 2026-09-06 --channels SHZ
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Supaya `python scripts/diagnose_fdsn_hourly.py` bisa dijalankan
# LANGSUNG dari root project tanpa perlu `python -m scripts...` atau
# set PYTHONPATH manual — root project (yang berisi folder `app/`)
# ditambahkan ke sys.path di sini, SEBELUM `import app...` di bawah.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import CACHE_WINDOW_SECONDS
from app.core.database import SessionLocal
from app.models.waveform import WaveformRecord
from app.services.waveform_storage_service import compute_hourly_windows


def hourly_windows_for_date(date_str):
    """Sama persis dengan compute_hourly_windows() yang dipakai
    aplikasi — window 24 jam UTC-aligned, dipecah selebar
    CACHE_WINDOW_SECONDS (biasanya 3600 = 1 jam), dari 00:00 sampai
    24:00 tanggal yang diberikan."""
    day_start = datetime.fromisoformat(date_str + "T00:00:00")
    day_end = day_start + timedelta(days=1)
    return compute_hourly_windows(day_start, day_end)


def check_db_window(db, network, station, location, channel, win_start, win_end):
    """Cek SATU window di DB. Dipakai LIKE (bukan '=='), persis sama
    dengan get_cached_channels_for_window() di
    waveform_storage_service.py — karena `location` yang sebenarnya
    tersimpan di DB adalah trace.stats.location (sering string kosong
    ""), sedangkan '*' hanya syntax wildcard permintaan. Pakai equality
    di sini akan salah mendiagnosis "MISSING" padahal sebenarnya ADA.

    Return (row_exists, file_exists, file_path_or_None).
    """
    location_pattern = location.replace("*", "%")
    channel_pattern = channel.replace("*", "%")

    record = (
        db.query(WaveformRecord)
        .filter(
            WaveformRecord.network == network,
            WaveformRecord.station == station,
            WaveformRecord.location.like(location_pattern),
            WaveformRecord.channel.like(channel_pattern),
            WaveformRecord.start_time == win_start,
            WaveformRecord.end_time == win_end,
        )
        .first()
    )
    if record is None:
        return False, False, None

    file_path = Path(record.file_path)
    return True, file_path.exists(), str(file_path)


def check_fdsn_live(network, station, location, channel, win_start, win_end):
    """Panggil BMKG (FDSN) LANGSUNG untuk SATU jam ini — bypass cache
    sepenuhnya, read-only, TIDAK disimpan ke DB/disk. Dipakai hanya
    untuk jam yang cache-nya tidak lengkap, supaya tahu apakah BMKG
    memang tidak punya data (wajar, permanen) atau ada masalah lain.

    Return (has_data: True/False/None, detail: str).
    None berarti gagal dicek (exception selain 'tidak ada data').
    """
    from obspy import UTCDateTime
    from obspy.clients.fdsn.header import FDSNNoDataException

    from app.core.fdsn_client import client

    try:
        stream = client.get_waveforms(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=UTCDateTime(win_start.isoformat()),
            endtime=UTCDateTime(win_end.isoformat()),
        )
        return True, f"{len(stream)} trace(s) dikembalikan BMKG"
    except FDSNNoDataException:
        return False, "FDSNNoDataException (BMKG memang tidak punya data jam ini)"
    except Exception as exc:  # noqa: BLE001 - diagnostic, tampilkan apa adanya
        return None, f"{type(exc).__name__}: {exc}"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--network", default="IA")
    parser.add_argument(
        "--station", required=True,
        help="SATU stasiun yang mau didiagnosis, mis. AAFM (bukan list).",
    )
    parser.add_argument("--location", default="*")
    parser.add_argument(
        "--channels", nargs="+", default=["SHZ", "SHE", "SHN"],
        help="Default sama dengan fdsn.channels di scenarios.json.",
    )
    parser.add_argument(
        "--date", required=True,
        help="Tanggal window 24 jam yang didiagnosis, format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--check-fdsn", action="store_true",
        help=(
            "Untuk tiap jam yang row/file cache-nya TIDAK lengkap, "
            "panggil BMKG (FDSN) LANGSUNG (read-only, bypass cache, "
            "TIDAK disimpan) untuk memastikan apakah BMKG memang tidak "
            "punya data jam itu, atau ada penyebab lain. Opsional "
            "karena ini live call ke BMKG, satu per jam bermasalah."
        ),
    )
    args = parser.parse_args()

    windows = hourly_windows_for_date(args.date)

    print(
        f"[CONFIG] network={args.network} station={args.station} "
        f"location={args.location} channels={args.channels} "
        f"date={args.date} n_windows={len(windows)} "
        f"(CACHE_WINDOW_SECONDS={CACHE_WINDOW_SECONDS})"
    )
    print(
        "[CONFIG] check_fdsn_live="
        + (
            "ON (live BMKG call untuk jam yang cache-nya bolong)"
            if args.check_fdsn
            else "OFF (tambahkan --check-fdsn untuk aktifkan)"
        )
        + "\n"
    )

    db = SessionLocal()
    problem_rows = []  # (channel, label_time, reason)

    try:
        for channel in args.channels:
            print(f"=== {args.network}.{args.station}.{args.location}.{channel} ===")
            for win_start, win_end in windows:
                row_exists, file_exists, file_path = check_db_window(
                    db, args.network, args.station, args.location, channel,
                    win_start, win_end,
                )
                label_time = f"{win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}"

                if row_exists and file_exists:
                    status = "OK        (row DB ada, file ada)"
                elif row_exists and not file_exists:
                    status = f"BROKEN    (row DB ada, TAPI file HILANG: {file_path})"
                else:
                    status = "MISSING   (belum pernah tersimpan ke cache)"

                print(f"  [{label_time}] {status}")

                if not (row_exists and file_exists):
                    reason = status.strip()
                    if args.check_fdsn:
                        has_data, detail = check_fdsn_live(
                            args.network, args.station, args.location, channel,
                            win_start, win_end,
                        )
                        if has_data is True:
                            reason += (
                                f" | FDSN LIVE: ADA data ({detail}) -> BMKG "
                                "sebenarnya punya data jam ini, artinya "
                                "download/save GAGAL secara tidak semestinya "
                                "(cek log backend saat window ini diproses)"
                            )
                        elif has_data is False:
                            reason += (
                                f" | FDSN LIVE: {detail} -> window ini "
                                "SECARA PERMANEN tidak akan pernah fully "
                                "cached untuk tanggal ini (wajar, bukan bug)"
                            )
                        else:
                            reason += f" | FDSN LIVE: gagal dicek ({detail})"
                    problem_rows.append((channel, label_time, reason))
    finally:
        db.close()

    print("\n=== RINGKASAN ===")
    if not problem_rows:
        print(
            "Semua jam x channel SUDAH fully cached (row DB + file ada). "
            "Kalau GET /api/waveform/status untuk window 24 jam ini MASIH "
            "melaporkan download_needed=True, kemungkinan besar argumen "
            "--location di script ini tidak match dengan yang dipakai "
            "benchmark/backend — jalankan ulang dengan --location yang "
            "sama persis dengan fdsn.location di scenarios.json."
        )
    else:
        print(
            f"Ditemukan {len(problem_rows)} kombinasi jam x channel "
            "BERMASALAH (penyebab window 24 jam ini tidak pernah fully "
            "cached):"
        )
        for channel, label_time, reason in problem_rows:
            print(f"  - {channel} @ {label_time}: {reason}")
        if not args.check_fdsn:
            print(
                "\nJalankan lagi dengan --check-fdsn untuk tahu apakah "
                "ini wajar (BMKG memang tak punya data jam itu) atau "
                "indikasi bug download/save."
            )


if __name__ == "__main__":
    main()