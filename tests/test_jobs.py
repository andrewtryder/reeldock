"""Tests for job status transitions and retry behavior."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from app.config import Settings
from app.db import get_async_session_factory, init_db
from app.models import JobStatus
from app.services.jobs import (
    DuplicateVideoError,
    InvalidJobUrlError,
    JobSubmitParams,
    submit_job,
)

# ── JobStatus enum ─────────────────────────────────────────────────────────────


def test_job_status_values():
    assert JobStatus.queued == "queued"
    assert JobStatus.running == "running"
    assert JobStatus.downloading == "downloading"
    assert JobStatus.postprocessing == "postprocessing"
    assert JobStatus.converting == "converting"
    assert JobStatus.verifying == "verifying"
    assert JobStatus.scanning == "scanning"
    assert JobStatus.succeeded == "succeeded"
    assert JobStatus.failed == "failed"
    assert JobStatus.cancelled == "cancelled"


def test_job_status_all_statuses():
    expected = {
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
    }
    actual = {s.value for s in JobStatus}
    assert actual == expected


# ── Job model ─────────────────────────────────────────────────────────────────


def test_job_duration_formatted_seconds():
    from app.models import Job

    job = Job()
    job.duration = 90
    assert job.duration_formatted == "1:30"


def test_job_duration_formatted_hours():
    from app.models import Job

    job = Job()
    job.duration = 3661
    assert job.duration_formatted == "1:01:01"


def test_job_duration_formatted_none():
    from app.models import Job

    job = Job()
    job.duration = None
    assert job.duration_formatted == "--:--"


# ── Retry logic ────────────────────────────────────────────────────────────────

TERMINAL_STATUSES = {JobStatus.failed, JobStatus.cancelled}
ACTIVE_STATUSES = {
    JobStatus.queued,
    JobStatus.running,
    JobStatus.downloading,
    JobStatus.postprocessing,
    JobStatus.converting,
    JobStatus.verifying,
    JobStatus.scanning,
}


def test_retry_only_allowed_for_terminal():
    """Only failed/cancelled jobs can be retried; others should not."""
    for status in ACTIVE_STATUSES:
        assert status not in TERMINAL_STATUSES

    for status in TERMINAL_STATUSES:
        assert status not in ACTIVE_STATUSES


def test_succeeded_job_not_retryable():
    assert JobStatus.succeeded not in TERMINAL_STATUSES


# ── Phase transitions ─────────────────────────────────────────────────────────


def test_expected_phase_progression():
    """Verify the happy-path phase order is defined correctly."""
    happy_path = [
        "queued",
        "running",
        "downloading",
        "postprocessing",
        "converting",
        "verifying",
        "scanning",
        "succeeded",
    ]
    # All phases should be valid JobStatus values
    valid = {s.value for s in JobStatus}
    for phase in happy_path:
        assert phase in valid


# ── submit_job service ───────────────────────────────────────────────────────


@pytest.fixture
def submit_job_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_settings: Settings):
    """Isolated SQLite DB for submit_job unit tests."""
    db_path = tmp_path / "submit-job.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import app.db as db_module

    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr("app.services.jobs.enqueue_job_task", lambda _job_id: "rq-test-1")
    monkeypatch.setattr("app.services.jobs.update_job_status", _noop)
    return default_settings


def _seed_imported_video(video_id: str) -> None:
    db_url = os.environ["DATABASE_URL"]
    prefix = "sqlite+aiosqlite:///"
    db_path = Path(db_url.removeprefix(prefix))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO imported_videos (video_id, job_id, source_url, source_title)
            VALUES (?, ?, ?, ?)
            """,
            (video_id, "existing-job", "https://www.youtube.com/watch?v=dup123", "Old Title"),
        )
        conn.commit()


@pytest.mark.asyncio
async def test_submit_job_invalid_url_raises(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=False, error="bad url")

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            with pytest.raises(InvalidJobUrlError, match="bad url"):
                await submit_job(
                    session,
                    submit_job_db,
                    JobSubmitParams(url="https://example.com/not-youtube"),
                )


@pytest.mark.asyncio
async def test_submit_job_duplicate_video_raises(submit_job_db: Settings):
    await init_db()
    _seed_imported_video("dup123")
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            with pytest.raises(DuplicateVideoError, match="already been imported"):
                await submit_job(
                    session,
                    submit_job_db,
                    JobSubmitParams(
                        url="https://www.youtube.com/watch?v=dup123",
                        video_id="dup123",
                    ),
                )


@pytest.mark.asyncio
async def test_submit_job_allows_reimport_when_flag_set(submit_job_db: Settings):
    await init_db()
    _seed_imported_video("dup123")
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=dup123",
                    video_id="dup123",
                    allow_reimport=True,
                ),
            )

    assert job.video_id == "dup123"
    assert rq_id == "rq-test-1"


@pytest.mark.asyncio
async def test_submit_job_new_folder_sets_destination(submit_job_db: Settings, tmp_path: Path):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    new_folder_name = "my-podcast"

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                    new_folder=new_folder_name,
                ),
            )

    assert job.destination_folder == new_folder_name
    assert (submit_job_db.output_root / new_folder_name).is_dir()
    assert rq_id == "rq-test-1"


@pytest.mark.asyncio
async def test_submit_omitted_dest_uses_channel_folder(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    submit_job_db.default_destination_folder = None

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, _rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                    channel="Some Channel",
                    uploader="Uploader Name",
                ),
            )

    assert job.destination_folder == "Some Channel"
    assert (submit_job_db.output_root / "Some Channel").is_dir()


@pytest.mark.asyncio
async def test_submit_job_omitted_dest_no_channel_root(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    submit_job_db.default_destination_folder = None

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, _rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                ),
            )

    assert job.destination_folder is None
    assert list(submit_job_db.output_root.iterdir()) == []


@pytest.mark.asyncio
async def test_submit_job_quoted_empty_stays_at_root(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    submit_job_db.default_destination_folder = None

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, _rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                    destination_folder="",
                    channel="Some Channel",
                ),
            )

    assert job.destination_folder is None
    assert not (submit_job_db.output_root / "Some Channel").exists()


@pytest.mark.asyncio
async def test_submit_keeps_named_folder_not_channel(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    submit_job_db.default_destination_folder = None
    named = "Theology"

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, _rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                    destination_folder=named,
                    channel="Some Channel",
                ),
            )

    assert job.destination_folder == named
    assert not (submit_job_db.output_root / "Some Channel").exists()


@pytest.mark.asyncio
async def test_submit_job_sanitizes_implicit_channel(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)
    submit_job_db.default_destination_folder = None

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            job, _rq_id = await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=abc123",
                    video_id="abc123",
                    channel="My: Channel",
                ),
            )

    assert job.destination_folder == "My Channel"
    assert (submit_job_db.output_root / "My Channel").is_dir()


@pytest.mark.asyncio
async def test_submit_job_in_progress_is_dup(submit_job_db: Settings):
    await init_db()
    mock_svc = Mock()
    mock_svc.validate_url.return_value = Mock(valid=True)

    with patch("app.services.jobs.YtDlpService", return_value=mock_svc):
        factory = get_async_session_factory()
        async with factory() as session:
            await submit_job(
                session,
                submit_job_db,
                JobSubmitParams(
                    url="https://www.youtube.com/watch?v=prog01",
                    video_id="prog01",
                ),
            )
            with pytest.raises(DuplicateVideoError, match="already being imported"):
                await submit_job(
                    session,
                    submit_job_db,
                    JobSubmitParams(
                        url="https://www.youtube.com/watch?v=prog01",
                        video_id="prog01",
                    ),
                )


@pytest.fixture
def jobs_live_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_settings: Settings):
    db_path = tmp_path / "jobs-live.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import app.db as db_module

    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    return default_settings


@pytest.mark.asyncio
async def test_retry_enqueue_failure_restores_failed_status(jobs_live_db: Settings):
    from app.models import Job, VideoImportClaim
    from app.services.jobs import retry_job

    await init_db()
    factory = get_async_session_factory()
    async with factory() as session:
        job = Job(
            id="retry-enq",
            url="https://www.youtube.com/watch?v=retry01",
            video_id="retry01",
            status=JobStatus.failed,
            phase="failed",
            error_message="download failed",
        )
        session.add(job)
        await session.commit()

        with (
            patch("app.services.jobs.enqueue_job_task", side_effect=RuntimeError("redis down")),
            pytest.raises(RuntimeError, match="redis down"),
        ):
            await retry_job(session, "retry-enq")

        restored = await session.get(Job, "retry-enq")
        assert restored is not None
        assert restored.status == JobStatus.failed
        assert restored.phase == "failed"
        assert await session.get(VideoImportClaim, "retry01") is None


@pytest.mark.asyncio
async def test_batch_enqueue_failure_marks_child_failed(jobs_live_db: Settings):
    from app.models import Job
    from app.services.jobs import BatchJobSubmitParams, submit_batch
    from app.services.ytdlp import PlaylistEntry

    await init_db()
    factory = get_async_session_factory()
    async with factory() as session:
        with patch("app.services.jobs.enqueue_job_task", side_effect=RuntimeError("redis down")):
            result = await submit_batch(
                session,
                jobs_live_db,
                BatchJobSubmitParams(
                    source_url="https://www.youtube.com/playlist?list=PLtest",
                    source_type="playlist",
                    batch_title="Batch",
                    entries=[
                        PlaylistEntry(
                            id="child01",
                            title="Child",
                            url="https://www.youtube.com/watch?v=child01",
                        )
                    ],
                ),
            )
        assert result.failed == 1
        assert result.created == 0
        child = await session.get(Job, result.job_ids[0]) if result.job_ids else None
        if child is None:
            from sqlalchemy import select

            child = (await session.execute(select(Job))).scalar_one()
        assert child.status == JobStatus.failed
        assert child.phase == "enqueue_failed"
