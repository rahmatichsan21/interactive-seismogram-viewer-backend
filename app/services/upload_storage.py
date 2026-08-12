import uuid

from obspy import Inventory, Stream


# Local Upload Storage — in-process dict, keyed by session_id.
# Terpisah dari Raw FDSN Cache (disk+MySQL) dan
# ProcessingCache (TTL/LRU untuk hasil processing).
upload_storage: dict[str, dict] = {}


def create_session():
    """Buat session_id baru dan entry kosong di storage."""
    session_id = uuid.uuid4().hex
    upload_storage[session_id] = {}
    return session_id


def store_stream(session_id, stream: Stream):
    """Simpan MiniSEED Stream ke session."""
    if session_id not in upload_storage:
        upload_storage[session_id] = {}
    upload_storage[session_id]["stream"] = stream


def store_inventory(session_id, inventory: Inventory):
    """Simpan StationXML Inventory ke session."""
    if session_id not in upload_storage:
        upload_storage[session_id] = {}
    upload_storage[session_id]["inventory"] = inventory


def get_stream(session_id):
    """Ambil Stream dari session. None jika tidak ada."""
    entry = upload_storage.get(session_id)
    if entry is None:
        return None
    return entry.get("stream")


def get_inventory(session_id):
    """Ambil Inventory dari session. None jika tidak ada."""
    entry = upload_storage.get(session_id)
    if entry is None:
        return None
    return entry.get("inventory")


def session_exists(session_id):
    return session_id in upload_storage


def remove_session(session_id):
    """Hapus session dan semua datanya."""
    upload_storage.pop(session_id, None)


def clear_all():
    """Hapus semua session (dipanggil saat backend restart)."""
    upload_storage.clear()
