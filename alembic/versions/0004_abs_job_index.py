"""Add Audiobookshelf per-job indexing status columns.

Revision ID: 0004_abs_job_index
Revises: 0003_import_ledger
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_abs_job_index"
down_revision: str | Sequence[str] | None = "0003_import_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("abs_library_id", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("abs_library_item_id", sa.String(length=64), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "abs_index_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column("jobs", sa.Column("abs_indexed_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("abs_index_error", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("abs_last_checked_at", sa.DateTime(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "abs_index_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "abs_index_attempts")
    op.drop_column("jobs", "abs_last_checked_at")
    op.drop_column("jobs", "abs_index_error")
    op.drop_column("jobs", "abs_indexed_at")
    op.drop_column("jobs", "abs_index_status")
    op.drop_column("jobs", "abs_library_item_id")
    op.drop_column("jobs", "abs_library_id")
