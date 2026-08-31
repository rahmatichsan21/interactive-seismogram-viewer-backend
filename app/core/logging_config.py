import logging
from logging.handlers import RotatingFileHandler

from app.core.config import BASE_DIR

LOG_DIR = BASE_DIR / "storage" / "logs"
LOG_FILE = LOG_DIR / "backend.log"

_LOG_FORMAT = (
    "%(asctime)s %(levelname)s "
    "[%(name)s.%(funcName)s] %(message)s"
)

_configured = False


def setup_logging(level=logging.INFO):
    """
    Konfigurasi logging backend.

    - File log (RotatingFileHandler) di storage/logs/backend.log
      agar tidak tumbuh tanpa batas.
    - Console handler hanya ditambahkan jika root belum punya handler
      (mis. saat dijalankan via uvicorn, uvicorn sudah memasang
      handler konsol sendiri — hindari log ganda).

    Dipanggil sekali saat backend start (app.main).
    """
    global _configured

    if _configured:
        return

    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Console hanya jika belum ada handler (konteks non-uvicorn/test).
    if not any(
        isinstance(h, logging.StreamHandler)
        for h in root.handlers
    ):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)