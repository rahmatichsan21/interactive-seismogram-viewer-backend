from datetime import datetime
from tempfile import SpooledTemporaryFile

from obspy import Stream, UTCDateTime

from app.models.download import DownloadTraceRequest
from app.services.upload_storage import get_stream as get_upload_stream
from app.services.waveform_provider_service import get_waveform


def _location_pattern(location):
    return "*" if not location or location == "--" else location


def load_export_stream(db, request):
    """Ambil raw Stream sesuai source dan daftar trace yang diminta."""
    if request.source == "local":
        if not request.session_id:
            raise ValueError("session_id is required for local source")
        raw_stream = get_upload_stream(request.session_id)
        if raw_stream is None:
            raise LookupError("Upload session not found")

        requested = request.traces or [
            DownloadTraceRequest(
                station="*",
                location=request.location,
                channel=ch,
            )
            for ch in request.channels
        ]
        selected = Stream()
        for trace_request in requested:
            for trace in raw_stream:
                if (
                    trace_request.station not in ("", "*")
                    and trace.stats.station != trace_request.station
                ):
                    continue
                if trace.stats.channel != trace_request.channel:
                    continue
                location = trace_request.location
                if location not in (None, "", "*") and location != "--" \
                        and trace.stats.location != location:
                    continue
                selected += trace.copy()
        return selected

    if not request.network or not request.start_time or not request.end_time:
        raise ValueError(
            "network, start_time, and end_time are required for FDSN"
        )

    requested = request.traces or [
        DownloadTraceRequest(
            station=station,
            location=request.location,
            channel=ch,
        )
        for station in request.stations
        for ch in request.channels
    ]
    selected = Stream()
    for trace_request in requested:
        selected += get_waveform(
            db=db,
            network=request.network,
            station=trace_request.station,
            location=_location_pattern(trace_request.location),
            channel=trace_request.channel,
            start_time=request.start_time,
            end_time=request.end_time,
        )
    return selected


def apply_export_trim(stream, trim_start, trim_end):
    if trim_start and trim_end:
        stream.trim(UTCDateTime(trim_start), UTCDateTime(trim_end))
    return stream


def write_mseed(stream):
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    stream.write(output, format="MSEED")
    output.seek(0)
    return output


def format_filename(request, stream):
    start = request.trim_start or request.start_time
    end = request.trim_end or request.end_time

    def timestamp(value):
        if not value:
            return "unknown"
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d_%H-%M"
        )

    # Build the station portion from the traces that are actually present
    # in the export stream. This excludes requested stations that returned
    # no waveform data and avoids inventing a separate metadata source.
    stations = sorted(
        {
            trace.stats.station
            for trace in stream
            if getattr(trace.stats, "station", "")
        },
        key=str.upper,
    )

    # A valid export stream should normally contain station metadata. Keep
    # the request as a defensive fallback for local data whose trace metadata
    # does not provide a station code.
    if not stations:
        stations = sorted(
            {station for station in request.stations if station},
            key=str.upper,
        )

    station_part = "_".join(stations) if stations else "UNKNOWN"

    return f"{station_part}_{timestamp(start)}_to_{timestamp(end)}.mseed"
