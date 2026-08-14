"""Coalesced batch Audiobookshelf scans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.config import Settings
from app.models import Base, ImportBatch, Job, JobStatus
from app.services.audiobookshelf import ScanResult
from app.services.batch_abs import (
    maybe_coalesce_batch_abs_scan,
    note_batch_child_finished,
    recover_stale_abs_leases,
    retry_batch_abs_scan,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def _mock_abs_enqueue():
    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        yield mock_enq


@pytest.fixture
def abs_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def abs_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.abs_base_url = "http://abs.local"
    s.abs_api_token = "abs-fixture-secret"
    s.abs_library_id = "lib-1"
    s.output_root = tmp_path / "media"
    s.work_dir = tmp_path / "work"
    return s


def _batch(session, batch_id: str = "batch-1", *, requested: bool = True) -> ImportBatch:
    batch = ImportBatch(
        id=batch_id,
        source_url="https://www.youtube.com/playlist?list=PLtest",
        source_type="playlist",
        title="Batch",
        requested_count=0,
        abs_scan_requested=requested,
    )
    session.add(batch)
    session.commit()
    return batch


def _child(
    session,
    batch_id: str,
    job_id: str,
    status: JobStatus,
    *,
    trigger: bool = True,
) -> Job:
    job = Job(
        id=job_id,
        url=f"https://youtube.com/watch?v={job_id}",
        video_id=job_id,
        status=status,
        batch_id=batch_id,
        trigger_abs_scan=trigger,
        output_title=job_id,
    )
    session.add(job)
    session.commit()
    return job


def _client(success: bool = True, skipped: bool = False, error: str | None = None) -> MagicMock:
    client = MagicMock()
    client.trigger_scan.return_value = ScanResult(success=success, skipped=skipped, error=error)
    return client


def test_one_child_one_scan(abs_db, abs_settings, _mock_abs_enqueue):
    _batch(abs_db)
    job = _child(abs_db, "batch-1", "c1", JobStatus.succeeded)
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, job, abs_settings)
    assert client.trigger_scan.call_count == 1
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    assert batch.abs_scan_status == "succeeded"
    assert batch.abs_scan_dirty is False
    _mock_abs_enqueue.assert_called_once_with("c1", attempt=0)
    abs_db.refresh(job)
    assert job.abs_index_status == "indexing"


def test_ten_successes_one_scan(abs_db, abs_settings, _mock_abs_enqueue):
    _batch(abs_db)
    client = _client()
    jobs = [_child(abs_db, "batch-1", f"c{i}", JobStatus.queued) for i in range(10)]
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        for index, job in enumerate(jobs):
            job.status = JobStatus.succeeded
            abs_db.commit()
            note_batch_child_finished(abs_db, job, abs_settings)
            if index < 9:
                assert client.trigger_scan.call_count == 0
    assert client.trigger_scan.call_count == 1
    assert _mock_abs_enqueue.call_count == 10


def test_mixed_results_one_scan_if_any_success(abs_db, abs_settings):
    _batch(abs_db)
    ok = _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    bad = _child(abs_db, "batch-1", "bad", JobStatus.failed)
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, ok, abs_settings)
        note_batch_child_finished(abs_db, bad, abs_settings)
    assert client.trigger_scan.call_count == 1


def test_all_failed_zero_scans(abs_db, abs_settings):
    _batch(abs_db)
    a = _child(abs_db, "batch-1", "a", JobStatus.failed)
    b = _child(abs_db, "batch-1", "b", JobStatus.cancelled)
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, a, abs_settings)
        note_batch_child_finished(abs_db, b, abs_settings)
    assert client.trigger_scan.call_count == 0


def test_concurrent_terminals_single_scan(abs_db, abs_settings):
    _batch(abs_db)
    _child(abs_db, "batch-1", "a", JobStatus.succeeded)
    _child(abs_db, "batch-1", "b", JobStatus.succeeded)
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    batch.abs_scan_dirty = True
    batch.abs_dirty_generation = 1
    batch.abs_scanned_generation = 0
    batch.abs_scan_status = "pending"
    abs_db.commit()
    client = _client()
    first = maybe_coalesce_batch_abs_scan(abs_db, "batch-1", abs_settings, client=client)
    second = maybe_coalesce_batch_abs_scan(abs_db, "batch-1", abs_settings, client=client)
    assert first is True
    assert second is False
    assert client.trigger_scan.call_count == 1


def test_scan_failure_leaves_jobs_succeeded(abs_db, abs_settings, _mock_abs_enqueue):
    _batch(abs_db)
    job = _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    client = _client(success=False, error="abs down")
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, job, abs_settings)
    abs_db.refresh(job)
    assert job.status == JobStatus.succeeded
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    assert batch.abs_scan_status == "failed"
    assert batch.abs_scan_error == "abs down"
    _mock_abs_enqueue.assert_not_called()
    assert job.abs_index_status == "not_requested"


def test_retry_after_failed_scan_runs_again(abs_db, abs_settings):
    _batch(abs_db)
    job = _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    failing = _client(success=False, error="temp")
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=failing):
        note_batch_child_finished(abs_db, job, abs_settings)
    ok_client = _client()
    retry_batch_abs_scan(abs_db, "batch-1", abs_settings, client=ok_client)
    assert ok_client.trigger_scan.call_count == 1
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    assert batch.abs_scan_status == "succeeded"


def test_later_child_retry_dirties_and_scans_again(abs_db, abs_settings):
    _batch(abs_db)
    first = _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    second = _child(abs_db, "batch-1", "later", JobStatus.failed)
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, first, abs_settings)
        note_batch_child_finished(abs_db, second, abs_settings)
    assert client.trigger_scan.call_count == 1
    second.status = JobStatus.succeeded
    abs_db.commit()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, second, abs_settings)
    assert client.trigger_scan.call_count == 2


def test_non_batch_job_does_not_coalesce(abs_db, abs_settings):
    job = Job(
        id="solo",
        url="https://youtube.com/watch?v=solo",
        video_id="solo",
        status=JobStatus.succeeded,
        trigger_abs_scan=True,
    )
    abs_db.add(job)
    abs_db.commit()
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, job, abs_settings)
    assert client.trigger_scan.call_count == 0


def test_unconfigured_abs_skips_scan(abs_db):
    settings = Settings()
    settings.abs_base_url = None
    settings.abs_api_token = None
    settings.abs_library_id = None
    _batch(abs_db)
    job = _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    client = _client()
    with patch("app.services.batch_abs.AudiobookshelfClient", return_value=client):
        note_batch_child_finished(abs_db, job, settings)
    assert client.trigger_scan.call_count == 0


def test_stale_running_lease_is_recovered(abs_db, abs_settings):
    _batch(abs_db)
    _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    batch.abs_scan_requested = True
    batch.abs_scan_dirty = True
    batch.abs_dirty_generation = 1
    batch.abs_scanned_generation = 0
    batch.abs_scan_status = "running"
    batch.abs_scan_lease_until = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=1)
    abs_db.commit()
    assert recover_stale_abs_leases(abs_db) == 1
    abs_db.commit()
    client = _client()
    assert maybe_coalesce_batch_abs_scan(abs_db, "batch-1", abs_settings, client=client) is True
    assert client.trigger_scan.call_count == 1


def test_mid_scan_child_success_runs_one_more_scan(abs_db, abs_settings):
    _batch(abs_db)
    _child(abs_db, "batch-1", "ok", JobStatus.succeeded)
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    batch.abs_scan_requested = True
    batch.abs_dirty_generation = 7
    batch.abs_scanned_generation = 6
    batch.abs_scan_dirty = True
    batch.abs_scan_status = "pending"
    abs_db.commit()

    factory = sessionmaker(bind=abs_db.bind)

    def trigger_scan() -> ScanResult:
        with factory() as other:
            row = other.get(ImportBatch, "batch-1")
            assert row is not None
            row.abs_dirty_generation = 8
            row.abs_scan_dirty = True
            other.commit()
        return ScanResult(success=True, skipped=False, error=None)

    client = MagicMock()
    client.trigger_scan.side_effect = trigger_scan
    assert maybe_coalesce_batch_abs_scan(abs_db, "batch-1", abs_settings, client=client) is True
    assert client.trigger_scan.call_count == 2
    batch = abs_db.get(ImportBatch, "batch-1")
    assert batch is not None
    assert batch.abs_scanned_generation == 8
    assert batch.abs_scan_dirty is False
    assert batch.abs_scan_status == "succeeded"
