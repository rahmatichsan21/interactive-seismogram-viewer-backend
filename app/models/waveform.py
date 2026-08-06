from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WaveformRecord(Base):
    __tablename__ = "waveform_records"

    # Mencegah duplikat: satu (network, station, location,
    # channel, start_time, end_time) hanya boleh ada SATU record
    # cache. Sebelumnya request yang sama bisa men-download dua
    # kali (mis. setelah file di-disk hilang lalu di-fetch ulang)
    # dan menyisipkan baris dobel untuk window yang sama.
    __table_args__ = (
        UniqueConstraint(
            "network",
            "station",
            "location",
            "channel",
            "start_time",
            "end_time",
            name="uq_waveform_records_cache_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    network: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    station: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    location: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    end_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )