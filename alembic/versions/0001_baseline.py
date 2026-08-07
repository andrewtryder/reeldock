"""Frozen baseline schema as of revision 0001_baseline.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-07

This revision must not import live ORM models. Future model changes belong in
later revisions; importing Base here would make fresh installs create tomorrow's
schema before those revisions run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=True),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("uploader", sa.Text(), nullable=True),
        sa.Column("uploader_id", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("upload_date", sa.String(length=16), nullable=True),
        sa.Column("chapter_count", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("output_title", sa.Text(), nullable=True),
        sa.Column("destination_folder", sa.Text(), nullable=True),
        sa.Column("final_output_path", sa.Text(), nullable=True),
        sa.Column("output_file_size", sa.Integer(), nullable=True),
        sa.Column("collision_mode", sa.String(length=20), nullable=False),
        sa.Column("audio_format", sa.Text(), nullable=True),
        sa.Column("audio_quality", sa.Text(), nullable=True),
        sa.Column("output_extension", sa.String(length=16), nullable=True),
        sa.Column("filename_template", sa.Text(), nullable=True),
        sa.Column("ytdlp_extra_args", sa.Text(), nullable=True),
        sa.Column("ffmpeg_extra_args", sa.Text(), nullable=True),
        sa.Column("cookies_file", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("loudness_normalize", sa.Boolean(), nullable=True),
        sa.Column("loudness_target_lufs", sa.Text(), nullable=True),
        sa.Column("loudness_audio_bitrate", sa.Text(), nullable=True),
        sa.Column("embed_metadata", sa.Boolean(), nullable=False),
        sa.Column("embed_thumbnail", sa.Boolean(), nullable=False),
        sa.Column("embed_chapters", sa.Boolean(), nullable=False),
        sa.Column("trigger_abs_scan", sa.Boolean(), nullable=False),
        sa.Column("allow_reimport", sa.Boolean(), nullable=False),
        sa.Column("sponsorblock_remove", sa.Boolean(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "downloading",
                "postprocessing",
                "converting",
                "verifying",
                "scanning",
                "succeeded",
                "failed",
                "cancelled",
                name="jobstatus",
            ),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=True),
        sa.Column("progress_eta", sa.String(length=32), nullable=True),
        sa.Column("progress_speed", sa.String(length=32), nullable=True),
        sa.Column("progress_label", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("work_dir", sa.Text(), nullable=True),
        sa.Column("log_file_path", sa.Text(), nullable=True),
        sa.Column("rq_job_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "imported_videos",
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("video_id"),
    )
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("rq_job_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_metadata", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("job_attempts")
    op.drop_table("imported_videos")
    op.drop_table("jobs")
    op.drop_table("import_batches")
    op.drop_table("app_settings")
