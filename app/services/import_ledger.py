"""Authoritative import ledger: claims, expiry, and crash recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import ImportedVideo, Job, JobStatus, VideoImportClaim

_TERMINAL = {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
_RECONCILE_PHASES = {"output_committed", "cleanup"}
_MIN_LEASE = timedelta(minutes=30)
_LEASE_BUFFER = timedelta(minutes=5)


def _naive_utc() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def claim_lease() -> timedelta:
    """Lease length: job timeout plus 5 minutes, never under 30 minutes."""
    from app.config import get_settings

    timeout = max(0, int(get_settings().job_timeout_seconds))
    return max(_MIN_LEASE, timedelta(seconds=timeout) + _LEASE_BUFFER)


def _takeover_predicate(video_id: str, job_id: str, now: datetime) -> ColumnElement[bool]:
    live_owner = exists().where(
        Job.id == VideoImportClaim.job_id,
        Job.status.notin_(_TERMINAL),
    )
    return and_(
        VideoImportClaim.video_id == video_id,
        or_(
            VideoImportClaim.job_id == job_id,
            and_(VideoImportClaim.expires_at <= now, ~live_owner),
        ),
    )


def _should_backfill_ledger(job: Job) -> bool:
    if job.status != JobStatus.succeeded:
        return False
    if not (job.video_id or "").strip():
        return False
    if job.phase == "skipped_collision":
        return False
    return job.owned_import is not False


def acquire_claim_sync(session: Session, video_id: str, job_id: str) -> bool:
    """Take or refresh an exclusive import lease for *video_id*."""
    normalized = (video_id or "").strip()
    if not normalized:
        return True
    expire_stale_claims_sync(session)
    now = _naive_utc()
    expires = now + claim_lease()
    existing = session.get(VideoImportClaim, normalized)
    if existing is None:
        try:
            with session.begin_nested():
                session.add(
                    VideoImportClaim(
                        video_id=normalized,
                        job_id=job_id,
                        claimed_at=now,
                        expires_at=expires,
                    )
                )
                session.flush()
        except IntegrityError:
            return False
        return True
    claimed = session.execute(
        update(VideoImportClaim)
        .where(_takeover_predicate(normalized, job_id, now))
        .values(job_id=job_id, claimed_at=now, expires_at=expires)
        .execution_options(synchronize_session="fetch")
    )
    return int(getattr(claimed, "rowcount", 0) or 0) == 1


def release_claim_sync(session: Session, video_id: str | None, job_id: str) -> None:
    """Drop the claim when this job still owns it."""
    normalized = (video_id or "").strip()
    if not normalized:
        return
    existing = session.get(VideoImportClaim, normalized)
    if existing is not None and existing.job_id == job_id:
        session.delete(existing)
        session.flush()


def renew_claim_sync(session: Session, video_id: str | None, job_id: str) -> None:
    """Extend the lease while this job still owns the claim."""
    normalized = (video_id or "").strip()
    if not normalized:
        return
    session.execute(
        update(VideoImportClaim)
        .where(
            VideoImportClaim.video_id == normalized,
            VideoImportClaim.job_id == job_id,
        )
        .values(expires_at=_naive_utc() + claim_lease())
        .execution_options(synchronize_session="fetch")
    )
    session.flush()


def expire_stale_claims_sync(session: Session) -> int:
    """Delete claims whose jobs are missing or already terminal.

    A still-running job keeps exclusivity even if the wall-clock lease lapsed.
    """
    claims = list(session.scalars(select(VideoImportClaim)).all())
    removed = 0
    for claim in claims:
        job = session.get(Job, claim.job_id)
        if job is None or job.status in _TERMINAL:
            session.delete(claim)
            removed += 1
    if removed:
        session.flush()
    return removed


def reconcile_import_state(session: Session) -> None:
    """Recover ledger/claim/job rows after a crash or worker restart."""
    expire_stale_claims_sync(session)
    succeeded = list(
        session.scalars(
            select(Job).where(
                Job.status == JobStatus.succeeded,
                Job.video_id.is_not(None),
            )
        ).all()
    )
    for job in succeeded:
        video_id = (job.video_id or "").strip()
        if not video_id or not _should_backfill_ledger(job):
            continue
        if session.get(ImportedVideo, video_id) is None:
            session.add(
                ImportedVideo(
                    video_id=video_id,
                    job_id=job.id,
                    source_url=job.url,
                    source_title=job.source_title,
                    imported_at=_naive_utc(),
                )
            )
        release_claim_sync(session, video_id, job.id)

    dangling = list(
        session.scalars(
            select(Job).where(
                Job.status.notin_(_TERMINAL),
                Job.phase.in_(_RECONCILE_PHASES),
                Job.video_id.is_not(None),
            )
        ).all()
    )
    for job in dangling:
        video_id = (job.video_id or "").strip()
        ledger = session.get(ImportedVideo, video_id) if video_id else None
        if ledger is not None and ledger.job_id == job.id:
            job.status = JobStatus.succeeded
            job.phase = "succeeded"
            job.finished_at = job.finished_at or _naive_utc()
            release_claim_sync(session, video_id, job.id)

    session.flush()


async def acquire_claim(session: AsyncSession, video_id: str, job_id: str) -> bool:
    """Async wrapper around exclusive claim insert/refresh."""
    normalized = (video_id or "").strip()
    if not normalized:
        return True
    await expire_stale_claims(session)
    now = _naive_utc()
    expires = now + claim_lease()
    existing = await session.get(VideoImportClaim, normalized)
    if existing is None:
        try:
            async with session.begin_nested():
                session.add(
                    VideoImportClaim(
                        video_id=normalized,
                        job_id=job_id,
                        claimed_at=now,
                        expires_at=expires,
                    )
                )
                await session.flush()
        except IntegrityError:
            return False
        return True
    claimed = await session.execute(
        update(VideoImportClaim)
        .where(_takeover_predicate(normalized, job_id, now))
        .values(job_id=job_id, claimed_at=now, expires_at=expires)
        .execution_options(synchronize_session="fetch")
    )
    return int(getattr(claimed, "rowcount", 0) or 0) == 1


async def release_claim(session: AsyncSession, video_id: str | None, job_id: str) -> None:
    normalized = (video_id or "").strip()
    if not normalized:
        return
    existing = await session.get(VideoImportClaim, normalized)
    if existing is not None and existing.job_id == job_id:
        await session.delete(existing)
        await session.flush()


async def expire_stale_claims(session: AsyncSession) -> int:
    result = await session.execute(select(VideoImportClaim))
    claims = list(result.scalars().all())
    removed = 0
    for claim in claims:
        job = await session.get(Job, claim.job_id)
        if job is None or job.status in _TERMINAL:
            await session.delete(claim)
            removed += 1
    if removed:
        await session.flush()
    return removed


async def reconcile_import_state_async(session: AsyncSession) -> None:
    await expire_stale_claims(session)
    result = await session.execute(
        select(Job).where(
            Job.status == JobStatus.succeeded,
            Job.video_id.is_not(None),
        )
    )
    for job in result.scalars().all():
        video_id = (job.video_id or "").strip()
        if not video_id or not _should_backfill_ledger(job):
            continue
        if await session.get(ImportedVideo, video_id) is None:
            session.add(
                ImportedVideo(
                    video_id=video_id,
                    job_id=job.id,
                    source_url=job.url,
                    source_title=job.source_title,
                    imported_at=_naive_utc(),
                )
            )
        await release_claim(session, video_id, job.id)
    dangling = await session.execute(
        select(Job).where(
            Job.status.notin_(_TERMINAL),
            Job.phase.in_(_RECONCILE_PHASES),
            Job.video_id.is_not(None),
        )
    )
    for job in dangling.scalars().all():
        video_id = (job.video_id or "").strip()
        ledger = await session.get(ImportedVideo, video_id) if video_id else None
        if ledger is not None and ledger.job_id == job.id:
            job.status = JobStatus.succeeded
            job.phase = "succeeded"
            job.finished_at = job.finished_at or _naive_utc()
            await release_claim(session, video_id, job.id)
    await session.flush()
