"""Add FK from extension_pairing_codes.paired_device_id to extension_devices.

Revision ID: 0006_pairing_device_fk_constraint
Revises: 0005_pairing_code_device_fk
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_pairing_device_fk_constraint"
down_revision: str | Sequence[str] | None = "0005_pairing_code_device_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_pairing_codes_paired_device_id"


def upgrade() -> None:
    op.execute(
        """
        UPDATE extension_pairing_codes
        SET paired_device_id = NULL
        WHERE paired_device_id IS NOT NULL
          AND paired_device_id NOT IN (SELECT id FROM extension_devices)
        """
    )
    with op.batch_alter_table("extension_pairing_codes") as batch_op:
        batch_op.create_foreign_key(
            _FK_NAME,
            "extension_devices",
            ["paired_device_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("extension_pairing_codes") as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
