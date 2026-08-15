"""Add paired_device_id to extension_pairing_codes.

Revision ID: 0005_pairing_code_device_fk
Revises: 0004_abs_job_index
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_pairing_code_device_fk"
down_revision: str | Sequence[str] | None = "0004_abs_job_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extension_pairing_codes",
        sa.Column("paired_device_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extension_pairing_codes", "paired_device_id")
