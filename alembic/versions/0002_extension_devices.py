"""Add extension device and pairing-code tables.

Revision ID: 0002_extension_devices
Revises: 0001_baseline
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_extension_devices"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_devices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_extension_devices_token_hash"),
    )
    op.create_table(
        "extension_pairing_codes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code_hmac", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.UniqueConstraint("code_hmac", name="uq_extension_pairing_codes_hmac"),
    )


def downgrade() -> None:
    op.drop_table("extension_pairing_codes")
    op.drop_table("extension_devices")
