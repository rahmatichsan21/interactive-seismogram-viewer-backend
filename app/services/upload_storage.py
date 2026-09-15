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


def store_inventory(
    session_id,
    inventory: Inventory,
    filename: str | None = None,
):
    """Tambah atau perbarui satu StationXML Inventory pada session."""
    if session_id not in upload_storage:
        upload_storage[session_id] = {}

    # Satu session local dapat memakai beberapa StationXML, misalnya
    # AAFM.xml dan ABJI.xml. Key nama file membuat upload ulang file
    # yang sama memperbarui inventory tersebut, bukan menduplikasinya.
    inventories = upload_storage[session_id].setdefault(
        "stationxml_inventories",
        {},
    )
    inventory_key = filename or f"stationxml-{len(inventories) + 1}"
    inventories[inventory_key] = inventory


def get_stream(session_id):
    """Ambil Stream dari session. None jika tidak ada."""
    entry = upload_storage.get(session_id)
    if entry is None:
        return None
    return entry.get("stream")


def get_inventory(session_id):
    """Ambil gabungan seluruh StationXML Inventory pada session."""
    entry = upload_storage.get(session_id)
    if entry is None:
        return None

    inventories = list(
        entry.get("stationxml_inventories", {}).values()
    )
    if not inventories:
        return None

    combined = inventories[0].copy()
    for inventory in inventories[1:]:
        combined = combined + inventory
    return combined


def get_stationxml_filenames(session_id):
    """Ambil seluruh nama StationXML yang tersimpan pada session."""
    entry = upload_storage.get(session_id)
    if entry is None:
        return []
    return list(
        entry.get("stationxml_inventories", {}).keys()
    )


def session_exists(session_id):
    return session_id in upload_storage


def remove_session(session_id):
    """Hapus session dan semua datanya."""
    upload_storage.pop(session_id, None)


def clear_all():
    """Hapus semua session (dipanggil saat backend restart)."""
    upload_storage.clear()
