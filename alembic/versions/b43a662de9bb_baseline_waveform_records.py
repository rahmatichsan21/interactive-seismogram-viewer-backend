"""baseline waveform_records

Revision ID: b43a662de9bb
Revises: 
Create Date: 2026-08-28 15:22:26.491345

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b43a662de9bb'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Baseline skema existing `waveform_records` (sudah ada di database
    # sebelum Alembic diperkenalkan). Migration ini TIDAK dijalankan lewat
    # `upgrade head` pada DB existing — database di-stamp ke revision ini
    # via `alembic stamp head`.
    op.create_table(
        "waveform_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("network", sa.String(length=20), nullable=False),
        sa.Column("station", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "network",
            "station",
            "location",
            "channel",
            "start_time",
            "end_time",
            name="uq_waveform_records_cache_key",
        ),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("waveform_records")
