import hashlib
import os
from pathlib import Path

from obspy import read_inventory

from app.core.config import BASE_DIR

# Direktori persistent Instrument Response Cache (StationXML).
# Dibuat otomatis saat runtime; masuk .gitignore seperti storage/waveforms.
RESPONSES_DIR = BASE_DIR / "storage" / "responses"


def make_key(
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    """
    Cache key identitas Instrument Response (bukan hasil processing).
    Mencakup seluruh parameter FDSN query yang menentukan response:
    network, station, location, channel, start/end time.
    TIDAK menyertakan filter/normalize/output unit/processing operation.
    """
    raw = "|".join([
        network or "",
        station or "",
        location or "",
        channel or "",
        start_time or "",
        end_time or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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