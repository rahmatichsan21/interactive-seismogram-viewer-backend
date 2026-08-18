from obspy import Stream

from app.processing.registry import OPERATION_REGISTRY
from app.models.processing import Operation
from app.services.processing_cache import processing_cache


def _is_expensive_boundary(ops_processed, op_type):
    """
    Replikasi persis kondisi "has_expensive" yang menentukan
    di titik mana snapshot ditulis (lihat apply_pipeline di
    bawah). Dipakai juga saat mencari checkpoint yang bisa
    dibaca, supaya titik-titik yang "dicari saat baca" selalu
    identik dengan titik-titik yang "ditulis saat proses".
    """
    return (
        any(op.type in ("filter",) for op in ops_processed)
        or op_type in ("filter",)
    )


def _find_reusable_checkpoint(cache_info, operations):
    """
    Cari checkpoint (prefix operations) TERPANJANG yang
    snapshot-nya masih ada di ProcessingCache, supaya
    apply_pipeline() bisa mulai dari situ alih-alih dari RAW.

    Scan maju dari awal operations, di tiap boundary yang
    valid (boundary yang sama seperti titik snapshot ditulis)
    hitung key via processing_cache.make_key() lalu cek
    processing_cache.has(key). Kandidat terakhir yang match
    = prefix terpanjang, karena scan berjalan maju.

    Return (index, ops_prefix) kalau ketemu, None kalau tidak
    ada checkpoint yang reusable (termasuk kalau cache_info
    None, snapshot expired/evicted, atau terjadi error saat
    mengecek cache — fallback selalu ke full pipeline).
    """
    if cache_info is None or not operations:
        return None

    best = None
    ops_processed = []

    for operation in operations:
        op_type = operation.type

        if ops_processed and _is_expensive_boundary(ops_processed, op_type):
            try:
                key = processing_cache.make_key(
                    network=cache_info["network"],
                    station=cache_info["station"],
                    channel=cache_info["channel"],
                    start_time=cache_info["start_time"],
                    end_time=cache_info["end_time"],
                    operations=ops_processed,
                )
                if processing_cache.has(key):
                    best = (len(ops_processed), list(ops_processed), key)
            except Exception:
                # Snapshot corrupt/error saat dicek -> jangan
                # dipakai, biarkan fallback ke full pipeline.
                pass

        ops_processed.append(operation)

    return best


def apply_pipeline(
    stream,
    operations: list[Operation],
    context=None,
    cache_info=None,
    ):
    """
    Terapkan pipeline processing ke Stream.

    cache_info (dict | None):
      {"network", "station", "start_time", "end_time"}
      Kalau diisi, snapshot full-resolution Stream akan
      disimpan ke ProcessingCache SEBELUM operation mahal
      (Filter, Instrument Correction) — sehingga Undo bisa
      melanjutkan dari snapshot tanpa replay dari Original.

      Kalau diisi, sebelum loop mulai, cari juga checkpoint
      TERPANJANG yang sudah ada snapshot-nya di
      ProcessingCache ([PROC SNAPSHOT HIT]) supaya operasi
      prefix yang identik tidak dijalankan ulang.
    """
    working_stream = stream
    ops_processed = []
    start_index = 0

    checkpoint = _find_reusable_checkpoint(cache_info, operations)
    if checkpoint is not None:
        prefix_len, prefix_ops, _key = checkpoint
        try:
            snapshot_key = processing_cache.make_key(
                network=cache_info["network"],
                station=cache_info["station"],
                channel=cache_info["channel"],
                start_time=cache_info["start_time"],
                end_time=cache_info["end_time"],
                operations=prefix_ops,
            )
            snapshot_stream = processing_cache.get(snapshot_key)
        except Exception:
            snapshot_stream = None

        if snapshot_stream is not None:
            working_stream = snapshot_stream
            ops_processed = prefix_ops
            start_index = prefix_len
            print(
                f"[PROC SNAPSHOT HIT] "
                f"{cache_info['network']}."
                f"{cache_info['station']}."
                f"{cache_info['channel']} "
                f"ops={[op.type for op in ops_processed]}"
            )

    for operation in operations[start_index:]:
        op_type = operation.type

        # Snapshot SEBELUM operation ini jika:
        # - ada operation sebelumnya (ops_processed tidak
        #   kosong), DAN
        # - operation sebelumnya atau operation ini sendiri
        #   adalah operation mahal (Filter, dsb).
        # Ini memungkinkan Undo mengambil state setelah
        # prefix yang mengandung Filter, baik operation
        # saat ini adalah Filter (Trim→Filter) maupun bukan
        # Filter (Filter→Trim).
        if cache_info is not None and ops_processed:
            has_expensive = (
                any(
                    op.type in ("filter",)
                    for op in ops_processed
                )
                or op_type in ("filter",)
            )

            if has_expensive:
                key = processing_cache.make_key(
                    network=cache_info["network"],
                    station=cache_info["station"],
                    channel=cache_info["channel"],
                    start_time=cache_info["start_time"],
                    end_time=cache_info["end_time"],
                    operations=ops_processed,
                )

                if not processing_cache.has(key):
                    processing_cache.put(
                        key,
                        Stream.copy(working_stream),
                    )
                    size_mb = sum(
                        tr.data.nbytes for tr in working_stream
                    ) / (1024 * 1024)
                    print(
                        f"[PROC SNAPSHOT] "
                        f"{cache_info['network']}."
                        f"{cache_info['station']}."
                        f"{cache_info['channel']} "
                        f"ops={[op.type for op in ops_processed]} "
                        f"size={size_mb:.1f}MB"
                    )

        handler = OPERATION_REGISTRY[op_type]
        working_stream = handler(
            working_stream,
            operation,
            context,
        )
        ops_processed.append(operation)

    return working_stream