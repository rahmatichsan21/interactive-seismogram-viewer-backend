import os
import re
import threading
from pathlib import Path

from obspy import read_inventory

from app.core.config import BASE_DIR
from app.services.inventory_service import get_inventory as get_fdsn_inventory
from app.services.response_cache import response_cache

# Direktori persistent Instrument Response Cache (StationXML).
# Dibuat otomatis saat runtime; masuk .gitignore seperti storage/waveforms.
RESPONSES_DIR = BASE_DIR / "storage" / "responses"

# Single-flight guard: mencegah dua request melakukan FDSN fetch untuk
# station yang sama secara bersamaan. RLock karena diakses bersarang
# (Condition berbasis lock yang sama untuk L1 get/put).
_fetch_lock = threading.RLock()
_fetch_cond = threading.Condition(_fetch_lock)
_in_flight = set()


def _sanitize(value):
    """Hanya karakter aman filesystem (alfanumerik, _, -)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value or "")


def filename_for(network, station):
    """
    Nama file StationXML per (network, station), tanpa ekstensi.
    Contoh: ('IA','AAFM') -> 'IA.AAFM' -> file 'IA.AAFM.xml'.
    Satu file mencakup semua channel & epoch response station;
    `inventory.get_response(seed_id, time)` memilih response yang benar
    berdasarkan channel + waktu. start/end waktu TIDAK masuk nama agar
    tidak membuat XML redundant per rentang waktu.
    """
    net = _sanitize(network)
    sta = _sanitize(station)
    return f"{net}.{sta}"


def _path_for(key):
    return RESPONSES_DIR / f"{key}.xml"


def get(key):
    """Ambil Inventory dari persistent StationXML. None jika MISS/error."""
    if not key:
        return None

    path = _path_for(key)

    try:
        if not path.exists():
            print(f"[PERSISTENT RESPONSE CACHE MISS] {key}")
            return None

        inventory = read_inventory(str(path))
        print(f"[PERSISTENT RESPONSE CACHE HIT] {key}")
        return inventory
    except Exception as exc:
        # Cache failure bukan alasan gagal Instrument Correction —
        # fallback ke FDSN/normal processing.
        print(f"[PERSISTENT RESPONSE CACHE ERROR] get {key}: {exc}")
        return None


def put(key, inventory):
    """Simpan Inventory sebagai StationXML (atomic write)."""
    if not key:
        return False

    try:
        RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

        target = _path_for(key)
        tmp = RESPONSES_DIR / f"{key}.xml.tmp"

        inventory.write(str(tmp), format="stationxml")

        # Atomic replace: hindari file setengah tertulis saat concurrent.
        os.replace(str(tmp), str(target))

        print(f"[PERSISTENT RESPONSE CACHE PUT] {key}")
        return True
    except Exception as exc:
        print(f"[PERSISTENT RESPONSE CACHE ERROR] put {key}: {exc}")
        return False


def _fetch_from_fdsn(network, station):
    """Fetch Instrument Response (level="response") semua channel station."""
    print(f"[FDSN RESPONSE FETCH] {network}.{station}")
    return get_fdsn_inventory(
        network=network,
        station=station,
        location="*",
        channel="*",
        level="response",
    )


def resolve_instrument_response(network, station):
    """
    Resolve Inventory Instrument Response utk SATU station.
    L1 (RAM) → L2 (persistent StationXML) → FDSN/BMKG.

    Single-flight: jika station yang sama sedang di-fetch oleh thread
    lain, request ini menunggu & memakai hasil yang sama (tidak fetch
    ganda). Failure-tolerant: kegagalan cache/fetch → log + return None.
    """
    key = filename_for(network, station)
    cache_key = (network, station)

    # L1 (in-memory, guarded oleh lock).
    with _fetch_lock:
        inventory = response_cache.get(cache_key)

    # L2 (persistent file) — read aman dari beberapa thread.
    if inventory is None:
        inventory = get(key)
        if inventory is not None:
            with _fetch_lock:
                response_cache.put(cache_key, inventory)

    if inventory is not None:
        return inventory

    # Fetch FDSN dengan single-flight.
    with _fetch_cond:
        while key in _in_flight:
            _fetch_cond.wait(timeout=0.5)

            with _fetch_lock:
                inventory = response_cache.get(cache_key)
            if inventory is None:
                inventory = get(key)
                if inventory is not None:
                    with _fetch_lock:
                        response_cache.put(cache_key, inventory)
            if inventory is not None:
                return inventory

        # Cek ulang setelah menunggu: thread lain mungkin sudah mengisi
        # cache (kasus sukses) — hindari fetch duplikat.
        with _fetch_lock:
            inventory = response_cache.get(cache_key)
        if inventory is None:
            inventory = get(key)
            if inventory is not None:
                with _fetch_lock:
                    response_cache.put(cache_key, inventory)
        if inventory is not None:
            return inventory

        _in_flight.add(key)

    try:
        try:
            inventory = _fetch_from_fdsn(network, station)
        except Exception as exc:
            print(f"[FDSN RESPONSE FETCH ERROR] {network}.{station}: {exc}")
            inventory = None

        if inventory is not None and len(inventory) > 0:
            put(key, inventory)
            with _fetch_lock:
                response_cache.put(cache_key, inventory)

        return inventory
    finally:
        with _fetch_cond:
            _in_flight.discard(key)
            _fetch_cond.notify_all()


def preload_instrument_response(network, station):
    """
    Preload best-effort untuk dipakai background (FastAPI BackgroundTasks):
    isi cache L1/L2 response station TANPA memengaruhi request utama.
    Selalu return tanpa raise (gagal → log).
    """
    try:
        resolve_instrument_response(network, station)
    except Exception as exc:
        print(
            f"[INSTRUMENT RESPONSE PRELOAD ERROR] "
            f"{network}.{station}: {exc}"
        )