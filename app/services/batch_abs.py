"""Coalesce Audiobookshelf scans for playlist/channel batches."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ImportBatch, Job, JobStatus
from app.services.audiobookshelf import AudiobookshelfClient

logger = logging.getLogger(__name__)

ABS_SCAN_LEASE = timedelta(minutes=10)
_TERMINAL = {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
_CLAIMABLE_STATUSES = ("pending", "failed")
_MAX_SCAN_ROUNDS = 8


def _naive_utc() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _as_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _sync_dirty_flag(batch: ImportBatch) -> None:
    batch.abs_scan_dirty = batch.abs_dirty_generation > batch.abs_scanned_generation


def recover_stale_abs_leases(session: Session) -> int:
    """Move expired running batch scans back to pending."""
    now = _naive_utc()
    batches = list(
        session.scalars(select(ImportBatch).where(ImportBatch.abs_scan_status == "running")).all()
    )
    recovered = 0
    for batch in batches:
        lease = _as_naive(batch.abs_scan_lease_until)
        if lease is None or lease <= now:
            batch.abs_scan_status = "pending"
            batch.abs_scan_lease_until = None
            recovered += 1
    if recovered:
        session.flush()
    return recovered


def mark_batch_dirty_if_needed(session: Session, job: Job) -> ImportBatch | None:
    """Record that a succeeded batch child needs a later ABS scan."""
    if not job.batch_id:
        return None
    batch = session.get(ImportBatch, job.batch_id)
    if batch is None:
        return None
    if job.status != JobStatus.succeeded:
        return batch
    if not (job.trigger_abs_scan or batch.abs_scan_requested):
        return batch
    now = _naive_utc()
    session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch.id)
        .values(abs_dirty_generation=ImportBatch.abs_dirty_generation + 1)
        .execution_options(synchronize_session="fetch")
    )
    session.refresh(batch)
    batch.abs_scan_requested = True
    _sync_dirty_flag(batch)
    if batch.abs_scan_requested_at is None:
        batch.abs_scan_requested_at = now
    if batch.abs_scan_status != "running":
        batch.abs_scan_status = "pending"
    session.flush()
    return batch


def _children_ready(session: Session, batch_id: str) -> bool:
    children = list(session.scalars(select(Job).where(Job.batch_id == batch_id)).all())
    if not children:
        return False
    if any(child.status not in _TERMINAL for child in children):
        return False
    return any(child.status == JobStatus.succeeded for child in children)


def _claim_batch_scan(session: Session, batch_id: str) -> bool:
    now = _naive_utc()
    result = session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .where(ImportBatch.abs_scan_requested.is_(True))
        .where(ImportBatch.abs_dirty_generation > ImportBatch.abs_scanned_generation)
        .where(
            or_(
                ImportBatch.abs_scan_status.in_(_CLAIMABLE_STATUSES),
                ImportBatch.abs_scan_status == "running",
            )
        )
        .where(
            or_(
                ImportBatch.abs_scan_status != "running",
                ImportBatch.abs_scan_lease_until.is_(None),
                ImportBatch.abs_scan_lease_until <= now,
            )
        )
        .values(
            abs_scan_status="running",
            abs_scan_started_at=now,
            abs_scan_lease_until=now + ABS_SCAN_LEASE,
            abs_scan_error=None,
            abs_claimed_generation=ImportBatch.abs_dirty_generation,
            abs_scan_dirty=True,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0) == 1


def maybe_coalesce_batch_abs_scan(
    session: Session,
    batch_id: str,
    settings: Settings,
    *,
    client: AudiobookshelfClient | None = None,
) -> bool:
    """Scan when every child is terminal and a newer dirty generation exists.

    Returns True when this caller performed at least one scan. A child that
    succeeds while a scan is in flight increments dirty_generation; after the
    claimed generation finishes we run one more scan.
    """
    recover_stale_abs_leases(session)
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        return False
    if not settings.abs_configured:
        return False
    if not (batch.abs_scan_requested and batch.abs_dirty_generation > batch.abs_scanned_generation):
        return False
    if not _children_ready(session, batch_id):
        return False

    scanner = client or AudiobookshelfClient(settings)
    scanned_any = False
    for _ in range(_MAX_SCAN_ROUNDS):
        if not _claim_batch_scan(session, batch_id):
            session.flush()
            return scanned_any
        session.commit()
        scanned_any = True

        scan = scanner.trigger_scan()
        finished = _naive_utc()
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            return True
        if scan.skipped or scan.success:
            batch.abs_scanned_generation = batch.abs_claimed_generation
            _sync_dirty_flag(batch)
            batch.abs_scan_error = None
            batch.abs_scan_finished_at = finished
            batch.abs_scan_lease_until = None
            if batch.abs_dirty_generation > batch.abs_scanned_generation:
                batch.abs_scan_status = "pending"
                session.commit()
                if not _children_ready(session, batch_id):
                    return True
                continue
            batch.abs_scan_status = "succeeded"
            session.commit()
            return True
        batch.abs_scan_status = "failed"
        batch.abs_scan_error = scan.error or "Audiobookshelf scan failed"
        batch.abs_scan_finished_at = finished
        batch.abs_scan_lease_until = None
        _sync_dirty_flag(batch)
        session.commit()
        return True
    return scanned_any


def note_batch_child_finished(session: Session, job: Job, settings: Settings) -> None:
    """Update batch ABS state after a child reaches a terminal status."""
    if not job.batch_id:
        return
    mark_batch_dirty_if_needed(session, job)
    session.commit()
    maybe_coalesce_batch_abs_scan(session, job.batch_id, settings)


def retry_batch_abs_scan(
    session: Session,
    batch_id: str,
    settings: Settings,
    *,
    client: AudiobookshelfClient | None = None,
) -> ImportBatch:
    """Idempotent manual retry of a coalesced batch ABS scan."""
    recover_stale_abs_leases(session)
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise LookupError(batch_id)
    now = _naive_utc()
    lease = _as_naive(batch.abs_scan_lease_until)
    if batch.abs_scan_status == "running" and lease is not None and lease > now:
        return batch
    if batch.abs_dirty_generation <= batch.abs_scanned_generation:
        batch.abs_dirty_generation = int(batch.abs_dirty_generation or 0) + 1
    batch.abs_scan_requested = True
    _sync_dirty_flag(batch)
    batch.abs_scan_status = "pending"
    if batch.abs_scan_requested_at is None:
        batch.abs_scan_requested_at = now
    session.commit()
    maybe_coalesce_batch_abs_scan(session, batch_id, settings, client=client)
    refreshed = session.get(ImportBatch, batch_id)
    if refreshed is None:
        raise LookupError(batch_id)
    return refreshed
