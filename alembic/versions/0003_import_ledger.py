"""Authoritative import ledger claims and coalesced batch ABS scans.

Revision ID: 0003_import_ledger
Revises: 0002_extension_devices
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_import_ledger"
down_revision: str | Sequence[str] | None = "0002_extension_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_import_claims",
        sa.Column("video_id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_scan_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_scan_dirty", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_dirty_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_scanned_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_claimed_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_batches",
        sa.Column("abs_scan_status", sa.String(length=16), nullable=False, server_default="idle"),
    )
    op.add_column("jobs", sa.Column("owned_import", sa.Boolean(), nullable=True))
    op.add_column("import_batches", sa.Column("abs_scan_error", sa.Text(), nullable=True))
    op.add_column(
        "import_batches", sa.Column("abs_scan_requested_at", sa.DateTime(), nullable=True)
    )
    op.add_column("import_batches", sa.Column("abs_scan_started_at", sa.DateTime(), nullable=True))
    op.add_column("import_batches", sa.Column("abs_scan_finished_at", sa.DateTime(), nullable=True))
    op.add_column("import_batches", sa.Column("abs_scan_lease_until", sa.DateTime(), nullable=True))

    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO imported_videos
                (video_id, job_id, source_url, source_title, imported_at)
            SELECT video_id, id, url, source_title,
                   COALESCE(finished_at, updated_at, CURRENT_TIMESTAMP)
            FROM jobs
            WHERE status = 'succeeded'
              AND video_id IS NOT NULL
              AND TRIM(video_id) != ''
              AND (phase IS NULL OR phase != 'skipped_collision')
              AND (owned_import IS NULL OR owned_import = 1)
            """
        )
    )


def downgrade() -> None:
    op.drop_column("import_batches", "abs_scan_lease_until")
    op.drop_column("import_batches", "abs_scan_finished_at")
    op.drop_column("import_batches", "abs_scan_started_at")
    op.drop_column("import_batches", "abs_scan_requested_at")
    op.drop_column("import_batches", "abs_scan_error")
    op.drop_column("import_batches", "abs_scan_status")
    op.drop_column("import_batches", "abs_scan_dirty")
    op.drop_column("import_batches", "abs_claimed_generation")
    op.drop_column("import_batches", "abs_scanned_generation")
    op.drop_column("import_batches", "abs_dirty_generation")
    op.drop_column("import_batches", "abs_scan_requested")
    op.drop_column("jobs", "owned_import")
    op.drop_table("video_import_claims")
