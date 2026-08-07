"""Frozen baseline schema as of revision 0001_baseline.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-07

Schema DDL lives in ``app.baseline_schema.BASELINE_METADATA``. That module is
immutable after 0001 ships and must not import live ORM models. Future model
changes belong in later Alembic revisions only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.baseline_schema import BASELINE_METADATA

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    BASELINE_METADATA.create_all(bind=op.get_bind())


def downgrade() -> None:
    BASELINE_METADATA.drop_all(bind=op.get_bind())
