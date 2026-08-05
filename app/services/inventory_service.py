import time

from app.core.fdsn_client import client
from obspy import UTCDateTime
from obspy.clients.fdsn.header import FDSNNoDataException
from app.core.config import (
    BMKG_URL,
    BMKG_USERNAME,
    BMKG_PASSWORD,
    INVENTORY_CACHE_TTL_SECONDS,
)



def get_inventory(
    network,
    station,
    location="*",
    channel="*",
    starttime=None,
    endtime=None,
    level="channel",
):
    return client.get_stations(
        network=network,
        station=station,
        location=location,
        channel=channel,
        starttime=starttime,
        endtime=endtime,
        level=level,
    )

def iter_networks(inventory):
    """
    Iterate over every network in an ObsPy Inventory.
    """
    for network in inventory:
        yield network


def iter_stations(inventory):
    """
    Iterate over every station in an ObsPy Inventory.
    """
    for network in inventory:
        for station in network:
            yield network, station


def iter_channels(inventory):
    """
    Iterate over every channel in an ObsPy Inventory.
    """
    for network in inventory:
        for station in network:
            for channel in station:
                yield network, station, channel

def unique_channels(inventory):
    """
    Return sorted unique channel codes.
    """
    return sorted({
        channel.code
        for _, _, channel in iter_channels(inventory)
    })

def unique_locations(inventory):
    """
    Return sorted unique location codes.
    """
    return sorted({
        channel.location_code or "--"
        for _, _, channel in iter_channels(inventory)
    })

def get_available_channels(
    network,
    station,
    start_time,
    end_time,
):
    inventory = get_inventory(
        network=network,
        station=station,
        location="*",
        channel="*",
        starttime=UTCDateTime(start_time),
        endtime=UTCDateTime(end_time),
        level="channel",
    )

    return unique_channels(inventory)


class InventoryUnavailableError(Exception):
    """
    Metadata channel tidak bisa diverifikasi (mis. BMKG timeout
    atau error jaringan lain, BUKAN kasus "tidak ada channel
    yang cocok").

    Dipakai untuk fail-closed Hard Limit di
    app/routers/processing.py: kalau keamanan suatu request
    tidak bisa dipastikan, request DITOLAK, bukan dilewatkan
    begitu saja.
    """


# Cache manual sederhana (dict + timestamp expiry), BUKAN
# cachetools.TTLCache - supaya tidak menambah dependency baru.
# Key sengaja TIDAK menyertakan start_time/end_time request:
# metadata channel di-fetch untuk SELURUH histori epoch-nya
# sekali saja, lalu difilter ke rentang waktu yang diminta di
# estimate_max_points_per_channel() secara in-memory. Kalau start/end
# request ikut jadi bagian key, cache ini akan kena masalah
# exact-match yang sama persis dengan yang kita perbaiki di
# waveform cache (Opsi D) - request dengan window sedikit
# berbeda akan selalu MISS walau station-nya sama.
#
# Catatan: ini in-memory PER PROCESS. Kalau nanti dijalankan
# multi-worker, tiap worker punya cache sendiri-sendiri (cold
# start per worker, tidak saling berbagi). Cukup untuk MVP;
# kalau nanti jadi masalah nyata, ini kandidat untuk dipindah
# ke cache bersama (mis. Redis) - bukan concern sekarang.
_channel_inventory_cache = {}


def _get_cached_channel_inventory(
    network,
    station,
    location,
    channel,
):
    cache_key = (network, station, location, channel)
    now = time.monotonic()

    cached = _channel_inventory_cache.get(cache_key)

    if cached is not None:
        inventory, expires_at = cached

        if now < expires_at:
            return inventory

    try:
        # starttime/endtime sengaja TIDAK dikirim di sini, supaya
        # yang di-cache adalah seluruh histori epoch channel ini,
        # bukan cuma epoch yang overlap dengan satu request saja.
        inventory = get_inventory(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=None,
            endtime=None,
            level="channel",
        )
    except FDSNNoDataException:
        # Bukan kegagalan verifikasi - ini memang tidak ada
        # channel yang cocok dengan pattern ini. Estimasi
        # otomatis akan menghasilkan 0 titik (lolos Hard Limit),
        # dan get_waveform() nanti yang akan menghasilkan error
        # "no data" yang lebih sesuai untuk kasus ini.
        inventory = None
    except Exception as exc:
        # BMKG timeout / error jaringan lain: keamanan request
        # ini TIDAK BISA diverifikasi. Fail-closed - jangan
        # simpan apa pun ke cache, biar percobaan berikutnya
        # mencoba fetch metadata lagi dari awal.
        raise InventoryUnavailableError(
            f"Gagal mengambil metadata channel untuk "
            f"{network}.{station}.{location}.{channel}: {exc}"
        ) from exc

    _channel_inventory_cache[cache_key] = (
        inventory,
        now + INVENTORY_CACHE_TTL_SECONDS,
    )

    return inventory


def estimate_max_points_per_channel(
    network,
    station,
    location,
    channel,
    start_time,
    end_time,
):
    """
    Estimasi titik data mentah dari CHANNEL TERBESAR saja (bukan
    dijumlah lintas semua channel yang match), TANPA mendownload
    waveform-nya sama sekali.

    Sengaja pakai max(), bukan sum(): sejak processing direfaktor
    jadi Sequential Per-Channel (lihat process_waveform_per_channel
    di processing_service.py), tiap channel diproses dan dilepas
    dari memori satu per satu - puncak RAM ditentukan oleh channel
    TERBESAR yang sedang diproses saat itu, bukan jumlah semua
    channel. Kalau fungsi ini masih pakai sum(), Hard Limit akan
    jadi terlalu konservatif (menolak request yang sebenarnya aman
    untuk arsitektur per-channel yang sekarang).

    Dipakai murni untuk Hard Limit check di /process - proteksi
    RAM sebelum fetch data sungguhan dijalankan. Sengaja tidak
    memperhitungkan operasi Trim yang mungkin ada di
    request.operations, karena stream.copy() pertama di
    process_waveform() terjadi SEBELUM operasi apa pun (termasuk
    Trim) berjalan - risiko memori sebenarnya ditentukan oleh
    rentang start_time/end_time request, bukan oleh hasil akhir
    setelah Trim.
    """
    request_start = UTCDateTime(start_time)
    request_end = UTCDateTime(end_time)
    duration_seconds = request_end - request_start

    if duration_seconds <= 0:
        raise ValueError(
            "end_time harus lebih besar dari start_time."
        )

    inventory = _get_cached_channel_inventory(
        network=network,
        station=station,
        location=location,
        channel=channel,
    )

    if inventory is None:
        return 0

    max_points = 0.0

    for _, _, channel_obj in iter_channels(inventory):
        channel_start = channel_obj.start_date
        channel_end = channel_obj.end_date  # None = masih aktif

        # Lewati epoch yang tidak overlap dengan rentang request.
        if (
            channel_start is not None
            and channel_start > request_end
        ):
            continue

        if (
            channel_end is not None
            and channel_end < request_start
        ):
            continue

        points_channel_ini = (
            channel_obj.sample_rate * duration_seconds
        )

        max_points = max(max_points, points_channel_ini)

    return int(max_points)