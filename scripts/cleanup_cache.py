import os
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.core.config import CACHE_CLEAR_AFTER_DAYS
from app.services.waveform_storage_service import (
    get_all_waveform_records_older_than,
)


def run_cleanup():
    db = SessionLocal()

    cutoff = datetime.now() - timedelta(days=CACHE_CLEAR_AFTER_DAYS)
    records = get_all_waveform_records_older_than(db, cutoff)

    print(
        f"[*] Retention: {CACHE_CLEAR_AFTER_DAYS} hari. "
        f"Cutoff: {cutoff.isoformat()}"
    )
    print(f"[*] Menemukan {len(records)} record kadaluarsa.")

    deleted_files = 0
    deleted_rows = 0

    for record in records:
        file_path = record.file_path

        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_files += 1
            except Exception as exc:
                print(
                    f"[-] Gagal hapus file {file_path}: {exc}"
                )

        db.delete(record)
        deleted_rows += 1

    db.commit()
    db.close()

    print(f"[+] File dihapus : {deleted_files}")
    print(f"[+] Row dihapus  : {deleted_rows}")
    print("[*] Cleanup selesai.")


if __name__ == "__main__":
    run_cleanup()
