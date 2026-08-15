"""Tests for Audiobookshelf post-scan indexing / reconcile."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.config import Settings
from app.models import (
    ABS_INDEX_FAILED,
    ABS_INDEX_INDEXED,
    ABS_INDEX_INDEXING,
    ABS_INDEX_NOT_FOUND,
    ABS_INDEX_NOT_REQUESTED,
    ABS_INDEX_SCAN_REQUESTED,
    Base,
    Job,
    JobStatus,
)
from app.services.abs_index import (
    RECONCILE_DELAYS_SECONDS,
    abs_reconcile_rq_job_id,
    check_job_abs_index_again,
    enqueue_reconcile,
    mark_batch_children_indexing,
    reconcile_abs_index,
    relative_output_path,
    request_scan_and_reconcile,
    resume_pending_abs_index,
    retry_job_abs_scan,
)
from app.services.audiobookshelf import ScanResult
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def idx_db():
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
def idx_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.abs_base_url = "http://abs.local"
    s.abs_api_token = "abs-fixture-secret"
    s.abs_library_id = "lib-1"
    s.output_root = tmp_path / "media"
    s.output_root.mkdir(parents=True, exist_ok=True)
    s.work_dir = tmp_path / "work"
    return s


def _job(
    session,
    job_id: str = "job-1",
    *,
    status: JobStatus = JobStatus.succeeded,
    final_path: str | None = None,
    title: str = "Scan Video",
) -> Job:
    job = Job(
        id=job_id,
        url=f"https://youtube.com/watch?v={job_id}",
        video_id=job_id,
        status=status,
        output_title=title,
        final_output_path=final_path,
        trigger_abs_scan=True,
    )
    session.add(job)
    session.commit()
    return job


def test_relative_output_path_inside_root(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    final = root / "Theology" / "Ep.m4b"
    assert relative_output_path(final, root) == "Theology/Ep.m4b"


def test_relative_output_path_outside_root(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    other = tmp_path / "elsewhere" / "Ep.m4b"
    assert relative_output_path(other, root) is None


def test_reconcile_delay_schedule():
    assert RECONCILE_DELAYS_SECONDS == (2, 5, 10, 20, 40)
    assert sum(RECONCILE_DELAYS_SECONDS) == 77


def test_enqueue_reconcile_uses_delay_and_deterministic_job_id():
    mock_queue = MagicMock()
    with (
        patch("app.queue.get_queue", return_value=mock_queue),
        patch("worker.tasks.reconcile_abs_index", create=True),
    ):
        assert enqueue_reconcile("job-x", attempt=2) is True
    mock_queue.enqueue_in.assert_called_once()
    delay = mock_queue.enqueue_in.call_args.args[0]
    assert delay == timedelta(seconds=10)
    assert mock_queue.enqueue_in.call_args.kwargs.get("job_id") == "abs-reconcile-job-x"
    assert mock_queue.enqueue_in.call_args.kwargs.get("args") == ("job-x", 2)


def test_reconcile_rq_job_id_is_legal_for_rq():
    from rq.job import validate_job_id

    validate_job_id(abs_reconcile_rq_job_id("550e8400-e29b-41d4-a716-446655440000"))
    with pytest.raises(ValueError, match="letters, numbers, underscores and dashes"):
        validate_job_id("abs-reconcile:job-x")


def test_enqueue_reconcile_stops_after_last():
    mock_queue = MagicMock()
    with patch("app.queue.get_queue", return_value=mock_queue):
        assert enqueue_reconcile("job-x", attempt=5) is False
    mock_queue.enqueue_in.assert_not_called()


def test_scan_fail_leaves_job_succeeded(idx_db, idx_settings):
    job = _job(idx_db)
    client = MagicMock()
    client.trigger_scan.return_value = ScanResult(success=False, error="ABS API returned 403")
    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        result = request_scan_and_reconcile(idx_db, job, idx_settings, client=client)
    idx_db.commit()
    idx_db.refresh(job)
    assert result.success is False
    assert job.status == JobStatus.succeeded
    assert job.abs_index_status == ABS_INDEX_FAILED
    assert job.abs_index_error == "ABS API returned 403"
    mock_enq.assert_not_called()


def test_scan_success_enqueues_reconcile(idx_db, idx_settings):
    job = _job(idx_db)
    client = MagicMock()
    client.trigger_scan.return_value = ScanResult(success=True)
    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        result = request_scan_and_reconcile(idx_db, job, idx_settings, client=client)
    idx_db.commit()
    idx_db.refresh(job)
    assert result.success is True
    assert job.abs_index_status == ABS_INDEX_SCAN_REQUESTED
    assert job.abs_library_id == "lib-1"
    mock_enq.assert_called_once_with(job.id, attempt=0)


def test_enqueue_failure_does_not_fail_import_job(idx_db, idx_settings):
    job = _job(idx_db)
    client = MagicMock()
    client.trigger_scan.return_value = ScanResult(success=True)
    mock_queue = MagicMock()
    mock_queue.enqueue_in.side_effect = ValueError(
        "Job ID must only contain letters, numbers, underscores and dashes"
    )
    with (
        patch("app.queue.get_queue", return_value=mock_queue),
        patch("worker.tasks.reconcile_abs_index", create=True),
    ):
        result = request_scan_and_reconcile(idx_db, job, idx_settings, client=client)
    idx_db.commit()
    idx_db.refresh(job)
    assert result.success is False
    assert job.status == JobStatus.succeeded
    assert job.abs_index_status == ABS_INDEX_FAILED
    assert job.abs_index_error == "Failed to schedule Audiobookshelf index check"


def test_reconcile_marks_indexed_on_match(idx_db, idx_settings, tmp_path: Path):
    final = idx_settings.output_root / "Theology" / "Scan Video.m4b"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"x")
    job = _job(idx_db, final_path=str(final))
    job.abs_index_status = ABS_INDEX_INDEXING
    job.abs_library_id = "lib-1"
    idx_db.commit()

    client = MagicMock()
    client.find_item_by_relative_path.return_value = {"id": "li-1"}

    with (
        patch("app.config.reload_settings", return_value=idx_settings),
        patch("app.db.get_sync_db", return_value=idx_db),
        patch("app.services.abs_index.AudiobookshelfClient", return_value=client),
        patch("app.services.abs_index._maybe_requeue") as mock_rq,
    ):
        # reconcile closes the session; keep ours open by stubbing close
        idx_db.close = MagicMock()  # type: ignore[method-assign]
        reconcile_abs_index(job.id, attempt=0)

    idx_db.refresh(job)
    assert job.abs_index_status == ABS_INDEX_INDEXED
    assert job.abs_library_item_id == "li-1"
    assert job.abs_indexed_at is not None
    mock_rq.assert_not_called()


def test_reconcile_exhausted_attempts_marks_not_found(idx_db, idx_settings):
    final = idx_settings.output_root / "Theology" / "Missing.m4b"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"x")
    job = _job(idx_db, "job-miss", final_path=str(final))
    job.abs_index_status = ABS_INDEX_SCAN_REQUESTED
    job.abs_library_id = "lib-1"
    idx_db.commit()

    client = MagicMock()
    client.find_item_by_relative_path.return_value = None

    with (
        patch("app.config.reload_settings", return_value=idx_settings),
        patch("app.db.get_sync_db", return_value=idx_db),
        patch("app.services.abs_index.AudiobookshelfClient", return_value=client),
        patch("app.services.abs_index.enqueue_reconcile") as mock_enq,
    ):
        idx_db.close = MagicMock()  # type: ignore[method-assign]
        reconcile_abs_index(job.id, attempt=4)  # last attempt index

    idx_db.refresh(job)
    assert job.abs_index_status == ABS_INDEX_NOT_FOUND
    assert "not appeared in Audiobookshelf" in (job.abs_index_error or "")
    assert job.status == JobStatus.succeeded
    mock_enq.assert_not_called()


def test_resume_pending_abs_index_skips_recent(idx_db, idx_settings):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(tz=UTC).replace(tzinfo=None)

    a = _job(idx_db, "a")
    a.abs_index_status = ABS_INDEX_SCAN_REQUESTED
    a.abs_last_checked_at = now - timedelta(seconds=120)  # stale

    b = _job(idx_db, "b")
    b.abs_index_status = ABS_INDEX_INDEXING
    b.abs_last_checked_at = None  # never checked

    recent = _job(idx_db, "recent")
    recent.abs_index_status = ABS_INDEX_INDEXING
    recent.abs_last_checked_at = now - timedelta(seconds=10)  # recently checked

    c = _job(idx_db, "c")
    c.abs_index_status = ABS_INDEX_INDEXED
    d = _job(idx_db, "d")
    d.abs_index_status = ABS_INDEX_NOT_REQUESTED
    idx_db.commit()

    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        count = resume_pending_abs_index(idx_db, idx_settings, stale_seconds=60)
    assert count == 2
    enqueued_ids = {call.args[0] for call in mock_enq.call_args_list}
    assert enqueued_ids == {"a", "b"}


def test_mark_batch_children_skips_dry_run(idx_db, idx_settings):
    from app.models import ImportBatch

    batch = ImportBatch(
        id="batch-1",
        source_url="https://www.youtube.com/playlist?list=PLx",
        source_type="playlist",
        title="B",
        requested_count=2,
    )
    idx_db.add(batch)
    ok = _job(idx_db, "ok")
    ok.batch_id = "batch-1"
    dry = _job(idx_db, "dry")
    dry.batch_id = "batch-1"
    dry.dry_run = True
    skip = _job(idx_db, "skip")
    skip.batch_id = "batch-1"
    skip.phase = "skipped_collision"
    idx_db.commit()

    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        marked = mark_batch_children_indexing(idx_db, "batch-1", idx_settings)
    idx_db.commit()
    assert marked == 1
    mock_enq.assert_called_once_with("ok", attempt=0)
    idx_db.refresh(ok)
    assert ok.abs_index_status == ABS_INDEX_INDEXING


def test_check_again_and_retry_helpers(idx_db, idx_settings):
    job = _job(idx_db)
    job.abs_index_status = ABS_INDEX_INDEXING
    idx_db.commit()
    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq:
        check_job_abs_index_again(idx_db, job, idx_settings)
    mock_enq.assert_called_once_with(job.id, attempt=0)

    client = MagicMock()
    client.trigger_scan.return_value = ScanResult(success=True)
    with patch("app.services.abs_index.enqueue_reconcile") as mock_enq2:
        retry_job_abs_scan(idx_db, job, idx_settings, client=client)
    mock_enq2.assert_called_once()
