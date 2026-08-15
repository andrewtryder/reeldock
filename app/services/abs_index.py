"""Audiobookshelf post-scan indexing / reconcile helpers."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    ABS_INDEX_FAILED,
    ABS_INDEX_INDEXED,
    ABS_INDEX_INDEXING,
    ABS_INDEX_NOT_FOUND,
    ABS_INDEX_SCAN_REQUESTED,
    Job,
    JobStatus,
)
from app.services.audiobookshelf import AudiobookshelfClient, ScanResult

logger = logging.getLogger(__name__)

# Bounded backoff before giving up (~77s of waits; transitions to not_found).
RECONCILE_DELAYS_SECONDS = (2, 5, 10, 20, 40)


def _naive_utc() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def relative_output_path(final_output_path: str | Path, output_root: str | Path) -> str | None:
    """Return output path relative to the library root, or None if outside root."""
    try:
        rel = Path(final_output_path).resolve().relative_to(Path(output_root).resolve())
    except ValueError, OSError:
        return None
    text = rel.as_posix()
    return text or None


def enqueue_reconcile(job_id: str, attempt: int = 0) -> None:
    """Schedule a delayed ABS index reconcile for *job_id*."""
    if attempt < 0 or attempt >= len(RECONCILE_DELAYS_SECONDS):
        return
    delay = RECONCILE_DELAYS_SECONDS[attempt]
    from worker.tasks import reconcile_abs_index

    from app.queue import get_queue

    rq_job_id = f"abs-reconcile:{job_id}"
    get_queue().enqueue_in(
        timedelta(seconds=delay),
        reconcile_abs_index,
        job_id,
        attempt,
        job_id=rq_job_id,
    )
    logger.debug("Enqueued ABS reconcile for job %s attempt=%s delay=%ss", job_id, attempt, delay)


def request_scan_and_reconcile(
    session: Session,
    job: Job,
    settings: Settings,
    client: AudiobookshelfClient | None = None,
) -> ScanResult:
    """Trigger an ABS scan for a single job and enqueue reconcile (non-blocking)."""
    now = _naive_utc()
    job.abs_library_id = settings.abs_library_id
    job.abs_last_checked_at = now
    job.abs_index_error = None

    scanner = client or AudiobookshelfClient(settings)
    if not settings.abs_configured:
        logger.info("ABS not configured; skipping scan/reconcile for job %s", job.id)
        session.flush()
        return ScanResult(success=False, skipped=True)

    result = scanner.trigger_scan(library_id=settings.abs_library_id)
    job.abs_last_checked_at = _naive_utc()

    if result.skipped:
        session.flush()
        return result

    if not result.success:
        job.abs_index_status = ABS_INDEX_FAILED
        job.abs_index_error = result.error or "Audiobookshelf scan failed"
        session.flush()
        return result

    job.abs_index_status = ABS_INDEX_SCAN_REQUESTED
    job.abs_index_error = None
    job.abs_index_attempts = 0
    session.flush()
    enqueue_reconcile(job.id, attempt=0)
    return result


def reconcile_abs_index(job_id: str, attempt: int = 0) -> None:
    """Worker entry: look up the job's output in ABS and update index status."""
    from app.config import reload_settings
    from app.db import get_sync_db

    settings = reload_settings()
    db = get_sync_db()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("ABS reconcile: job %s not found", job_id)
            return
        if job.abs_index_status == ABS_INDEX_INDEXED:
            return
        if job.abs_index_status == ABS_INDEX_FAILED:
            return
        if job.status != JobStatus.succeeded:
            return

        now = _naive_utc()
        job.abs_index_status = ABS_INDEX_INDEXING
        job.abs_last_checked_at = now
        job.abs_index_attempts = int(job.abs_index_attempts or 0) + 1
        db.commit()

        rel = relative_output_path(job.final_output_path or "", settings.output_root)
        if not rel:
            logger.info("ABS reconcile: job %s has no relative output path", job_id)
            if attempt + 1 >= len(RECONCILE_DELAYS_SECONDS):
                job.abs_index_status = ABS_INDEX_NOT_FOUND
                job.abs_index_error = (
                    "Audiobook created, but it has not appeared in Audiobookshelf yet."
                )
                db.commit()
                return
            db.commit()
            _maybe_requeue(job_id, attempt)
            return

        library_id = job.abs_library_id or settings.abs_library_id
        if not library_id or not settings.abs_configured:
            logger.info("ABS reconcile: job %s missing library/config", job_id)
            return

        client = AudiobookshelfClient(settings)
        title_hint = job.output_title or job.source_title
        match = client.find_item_by_relative_path(library_id, rel, title_hint=title_hint)
        job = db.get(Job, job_id)
        if job is None:
            return
        job.abs_last_checked_at = _naive_utc()

        if match and match.get("id"):
            job.abs_index_status = ABS_INDEX_INDEXED
            job.abs_library_item_id = str(match["id"])
            job.abs_library_id = library_id
            job.abs_indexed_at = job.abs_last_checked_at
            job.abs_index_error = None
            db.commit()
            logger.info("ABS reconcile: job %s indexed as %s", job_id, job.abs_library_item_id)
            return

        if attempt + 1 >= len(RECONCILE_DELAYS_SECONDS):
            job.abs_index_status = ABS_INDEX_NOT_FOUND
            job.abs_index_error = (
                "Audiobook created, but it has not appeared in Audiobookshelf yet."
            )
            db.commit()
            logger.info(
                "ABS reconcile: job %s still missing after %s attempts; marked not_found",
                job_id,
                attempt + 1,
            )
            return

        job.abs_index_status = ABS_INDEX_INDEXING
        db.commit()
        _maybe_requeue(job_id, attempt)
    except Exception:
        logger.exception("ABS reconcile failed for job %s", job_id)
        with contextlib.suppress(Exception):
            db.rollback()
    finally:
        db.close()


def _maybe_requeue(job_id: str, attempt: int) -> None:
    next_attempt = attempt + 1
    if next_attempt >= len(RECONCILE_DELAYS_SECONDS):
        return
    enqueue_reconcile(job_id, attempt=next_attempt)


def resume_pending_abs_index(session: Session, settings: Settings, stale_seconds: int = 60) -> int:
    """Re-enqueue jobs waiting on ABS index after worker restart (only stale / unchecked)."""
    if not settings.abs_configured:
        return 0
    cutoff = _naive_utc() - timedelta(seconds=stale_seconds)
    pending = list(
        session.scalars(
            select(Job).where(
                Job.abs_index_status.in_((ABS_INDEX_SCAN_REQUESTED, ABS_INDEX_INDEXING)),
                Job.status == JobStatus.succeeded,
                (Job.abs_last_checked_at.is_(None)) | (Job.abs_last_checked_at < cutoff),
            )
        ).all()
    )
    resumed = 0
    for job in pending:
        attempt = min(int(job.abs_index_attempts or 0), len(RECONCILE_DELAYS_SECONDS) - 1)
        enqueue_reconcile(job.id, attempt=attempt)
        resumed += 1
    return resumed


def mark_batch_children_indexing(
    session: Session,
    batch_id: str,
    settings: Settings,
) -> int:
    """After a coalesced batch scan succeeds, enqueue reconcile for eligible children."""
    if not settings.abs_configured:
        return 0
    children = list(session.scalars(select(Job).where(Job.batch_id == batch_id)).all())
    now = _naive_utc()
    marked = 0
    for job in children:
        if job.status != JobStatus.succeeded:
            continue
        if job.phase == "skipped_collision":
            continue
        if job.dry_run:
            continue
        if job.abs_index_status == ABS_INDEX_INDEXED:
            continue
        job.abs_library_id = settings.abs_library_id
        job.abs_index_status = ABS_INDEX_INDEXING
        job.abs_index_error = None
        job.abs_last_checked_at = now
        job.abs_index_attempts = 0
        session.flush()
        enqueue_reconcile(job.id, attempt=0)
        marked += 1
    return marked


def retry_job_abs_scan(
    session: Session,
    job: Job,
    settings: Settings,
    *,
    client: AudiobookshelfClient | None = None,
) -> ScanResult:
    """Idempotent manual re-scan + reconcile for a single job."""
    if job.batch_id:
        # Batch scans are coalesced separately; still allow per-job re-index.
        job.abs_index_status = ABS_INDEX_SCAN_REQUESTED
        job.abs_index_error = None
        job.abs_library_id = settings.abs_library_id
        job.abs_last_checked_at = _naive_utc()
        job.abs_index_attempts = 0
        session.flush()
        scanner = client or AudiobookshelfClient(settings)
        result = scanner.trigger_scan(library_id=settings.abs_library_id)
        if result.success:
            job.abs_index_status = ABS_INDEX_INDEXING
            session.flush()
            enqueue_reconcile(job.id, attempt=0)
        elif not result.skipped:
            job.abs_index_status = ABS_INDEX_FAILED
            job.abs_index_error = result.error or "Audiobookshelf scan failed"
            session.flush()
        return result
    return request_scan_and_reconcile(session, job, settings, client=client)


def check_job_abs_index_again(
    session: Session,
    job: Job,
    settings: Settings,
) -> None:
    """Idempotent manual re-check without requesting a new library scan."""
    if job.abs_index_status == ABS_INDEX_INDEXED:
        return
    if job.status != JobStatus.succeeded:
        return
    job.abs_index_status = ABS_INDEX_INDEXING
    job.abs_index_error = None
    job.abs_last_checked_at = _naive_utc()
    session.flush()
    enqueue_reconcile(job.id, attempt=0)
