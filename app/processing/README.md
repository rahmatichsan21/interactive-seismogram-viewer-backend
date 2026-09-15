# `app/processing`

Folder ini mengimplementasikan pipeline operation ObsPy. Router processing
menyediakan stream dan context; service processing mengatur per-trace/gap;
pipeline ini menerapkan operation sesuai urutan request.

```text
processing/
├── registry.py        # type operation -> handler
├── pipeline.py        # menerapkan operation berurutan
└── operations/
    ├── trim.py
    ├── filter.py
    └── instrument_correction.py
```

## Operation saat ini

- `trim`: memotong waveform menurut start/end time.
- `filter`: lowpass, highpass, atau bandpass.
- `instrument_correction`: `remove_response()` menjadi DISP, VEL, atau ACC.

## Gap handling

Pipeline handler beroperasi pada segmen valid ketika trace memiliki gap.
`processing_service` melakukan alur `split()` → process tiap segmen →
`merge(fill_value=0)`. Jangan memindahkan merge nol ke sebelum operation;
masked trace tidak aman langsung difilter atau dikoreksi response-nya.

## Menambah operation

1. Tambahkan schema di `app/models/processing.py`.
2. Tambahkan handler di `operations/`.
3. Daftarkan handler pada `registry.py`.
4. Pastikan context yang dibutuhkan tersedia dari router/service.
5. Tambahkan mapping payload dan UI frontend bila operation diekspos ke user.
