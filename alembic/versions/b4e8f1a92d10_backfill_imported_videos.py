"""backfill imported_videos from historical succeeded jobs

Revision ID: b4e8f1a92d10
Revises: 90d922c029c3
Create Date: 2026-07-03 07:42:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "b4e8f1a92d10"
down_revision: str | Sequence[str] | None = "90d922c029c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill canonical import ledger from historical successful jobs."""
    op.execute(
        text(
            """
            INSERT OR IGNORE INTO imported_videos (
                video_id,
                job_id,
                source_url,
                source_title,
                imported_at
            )
            SELECT
                video_id,
                id,
                url,
                source_title,
                COALESCE(finished_at, created_at, CURRENT_TIMESTAMP)
            FROM jobs
            WHERE status = 'succeeded'
              AND video_id IS NOT NULL
              AND TRIM(video_id) != ''
            """
        )
    )


def downgrade() -> None:
    """Data backfill is irreversible."""
