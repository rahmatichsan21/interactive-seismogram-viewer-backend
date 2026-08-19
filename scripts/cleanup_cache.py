from app.services.waveform_storage_service import (
    run_waveform_cache_cleanup,
    set_last_cleanup_date,
)


def run_cleanup():
    deleted_files, deleted_rows = run_waveform_cache_cleanup()
    set_last_cleanup_date()

    print("[CACHE CLEANUP] Running manual cleanup")
    print(f"[CACHE CLEANUP] Removed {deleted_files} files")
    print(
        f"[CACHE CLEANUP] Removed "
        f"{deleted_rows} database records"
    )
    print("[CACHE CLEANUP] Completed")


if __name__ == "__main__":
    run_cleanup()
