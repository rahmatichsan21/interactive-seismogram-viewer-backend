from obspy.clients.fdsn import Client

from app.core.config import (
    BMKG_URL,
    BMKG_USERNAME,
    BMKG_PASSWORD,
    FDSN_TIMEOUT_SECONDS,
)

client = Client(
    BMKG_URL,
    user=BMKG_USERNAME,
    password=BMKG_PASSWORD,
    timeout=FDSN_TIMEOUT_SECONDS,
)