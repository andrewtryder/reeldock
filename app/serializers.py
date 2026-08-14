"""API serialization helpers."""

from __future__ import annotations

from typing import Any

from app.models import Job


def job_dict(job: Job) -> dict[str, Any]:
    # Read batch only from the instance dict so we never trigger a lazy load.
    # Async handlers (especially WebSockets under Starlette's TestClient) hang
    # when SQLAlchemy tries to lazy-load relationships.
    batch = job.__dict__.get("batch")
    batch_title = batch.title if batch is not None else None

    return {
        "id": job.id,
        "url": job.url,
        "video_id": job.video_id,
        "source_title": job.source_title,
        "output_title": job.output_title,
        "destination_folder": job.destination_folder,
        "final_output_path": job.final_output_path,
        "output_file_size": job.output_file_size,
        "status": job.status,
        "phase": job.phase,
        "progress": job.progress,
        "progress_percent": job.progress_percent,
        "progress_eta": job.progress_eta,
        "progress_speed": job.progress_speed,
        "progress_label": job.progress_label,
        "error_message": job.error_message,
        "attempts": job.attempts,
        "chapter_count": job.chapter_count,
        "allow_reimport": job.allow_reimport,
        "duration": job.duration,
        "uploader": job.uploader,
        "uploader_id": job.uploader_id,
        "channel": job.channel,
        "channel_id": job.channel_id,
        "thumbnail_url": job.thumbnail_url,
        "batch_id": job.batch_id,
        "batch_title": batch_title,
        "rq_job_id": job.rq_job_id,
        "log_file_path": job.log_file_path,
        "trigger_abs_scan": job.trigger_abs_scan,
        "abs_library_id": job.abs_library_id,
        "abs_library_item_id": job.abs_library_item_id,
        "abs_index_status": job.abs_index_status,
        "abs_indexed_at": job.abs_indexed_at.isoformat() if job.abs_indexed_at else None,
        "abs_index_error": job.abs_index_error,
        "abs_last_checked_at": (
            job.abs_last_checked_at.isoformat() if job.abs_last_checked_at else None
        ),
        "abs_index_attempts": job.abs_index_attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def extension_job_dict(job: Job) -> dict[str, Any]:
    """Slim job payload for the extension control plane.

    Omits filesystem paths, RQ internals, and config fields the popup
    does not need.
    """
    return {
        "id": job.id,
        "status": job.status,
        "phase": job.phase,
        "title": job.output_title or job.source_title,
        "uploader": job.uploader,
        "progress": job.progress,
        "progress_percent": job.progress_percent,
        "progress_eta": job.progress_eta,
        "progress_speed": job.progress_speed,
        "progress_label": job.progress_label,
        "error_message": job.error_message,
        "destination_folder": job.destination_folder or "",
        "job_url": f"/jobs/{job.id}",
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
