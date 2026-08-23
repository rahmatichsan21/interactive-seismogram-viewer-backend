from obspy import Stream

from app.models.processing import InstrumentCorrectionOperation

# Mapping unit output -> label yang ditampilkan/dikirim ke frontend.
OUTPUT_UNITS = {
    "DISP": "m",
    "VEL": "m/s",
    "ACC": "m/s\u00b2",
}


def apply_instrument_correction(
    stream,
    operation: InstrumentCorrectionOperation,
    context,
):
    """
    Remove instrument response dari setiap trace menggunakan
    `Trace.remove_response(...)`.

    Response dicocokkan PER TRACE oleh ObsPy lewat
    `inventory.get_response(seed_id, starttime)` — identity lengkap
    network.station.location.channel + waktu. Bukan channel saja.

    Inventory diambil dari `context["inventory"]` (di-resolve di
    router processing: Local dari session StationXML, FDSN dari
    `level="response"`).
    """
    context = context or {}
    inventory = context.get("inventory")

    if inventory is None:
        raise ValueError(
            "Instrument response tidak tersedia. "
            "Upload StationXML (Local) atau pastikan response "
            "FDSN dapat diambil."
        )

    # Validasi pre_filt sebelum processing.
    pre_filt = operation.pre_filt
    if pre_filt is not None:
        if len(pre_filt) != 4:
            raise ValueError(
                "pre_filt harus terdiri dari 4 frekuensi "
                "[f1, f2, f3, f4]."
            )
        f1, f2, f3, f4 = pre_filt
        if not (f1 < f2 < f3 < f4):
            raise ValueError(
                "pre_filt harus memenuhi f1 < f2 < f3 < f4."
            )

    if operation.water_level is not None and operation.water_level < 0:
        raise ValueError("water_level tidak boleh negatif.")

    working_stream = stream.copy()
    corrected = Stream()

    for trace in working_stream:
        nyquist = trace.stats.sampling_rate / 2

        if pre_filt is not None and pre_filt[3] >= nyquist:
            raise ValueError(
                f"{trace.id}: pre_filt f4 ({pre_filt[3]} Hz) "
                f"harus lebih kecil dari Nyquist ({nyquist:.2f} Hz)."
            )

        # Pastikan response cocok dengan identity trace + waktu.
        # get_response melempar exception bila tidak ditemukan atau
        # tidak berlaku pada waktu waveform.
        inventory.get_response(
            trace.id,
            trace.stats.starttime,
        )

        trace.remove_response(
            inventory=inventory,
            output=operation.output,
            water_level=operation.water_level,
            pre_filt=tuple(pre_filt) if pre_filt else None,
            zero_mean=True,
            taper=True,
            taper_fraction=0.05,
            plot=False,
        )

        # Simpan metadata unit hasil correction supaya trace_to_json
        # bisa meneruskan ke frontend. Identity stats tidak berubah.
        trace.stats.units = {
            "output": operation.output,
            "type": OUTPUT_UNITS.get(operation.output, ""),
        }

        corrected.append(trace)

    return corrected