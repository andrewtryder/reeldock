"""Coverage for worker.tasks.run_import_job (missing job, success, failure)."""

from __future__ import annotations

from unittest.mock import Mock

from app.models import JobStatus
from worker.tasks import run_import_job


def test_run_import_job_missing_job_returns_without_pipeline(monkeypatch):
    db = Mock()
    monkeypatch.setattr("worker.tasks.reload_settings", lambda: Mock())
    monkeypatch.setattr("worker.tasks.get_sync_db", lambda: db)
    monkeypatch.setattr("worker.tasks.sync_get_job", lambda _db, _job_id: None)
    pipeline_cls = Mock()
    monkeypatch.setattr("worker.tasks.ImportPipeline", pipeline_cls)

    run_import_job("missing-job")

    pipeline_cls.assert_not_called()
    db.close.assert_called_once()


def test_run_import_job_runs_pipeline(monkeypatch):
    db = Mock()
    job = Mock()
    pipeline = Mock()
    monkeypatch.setattr("worker.tasks.reload_settings", lambda: Mock())
    monkeypatch.setattr("worker.tasks.get_sync_db", lambda: db)
    monkeypatch.setattr(
        "worker.tasks.sync_get_job",
        lambda _db, job_id: job if job_id == "job-1" else None,
    )
    monkeypatch.setattr("worker.tasks.ImportPipeline", lambda _db, _settings, job_id: pipeline)

    run_import_job("job-1")

    pipeline.run.assert_called_once()
    db.close.assert_called_once()


def test_run_import_job_records_failure_then_closes(monkeypatch):
    db = Mock()
    job = Mock()
    job.status = JobStatus.running
    pipeline = Mock()
    pipeline.run.side_effect = RuntimeError("pipeline exploded")
    update = Mock()
    record = Mock()
    monkeypatch.setattr("worker.tasks.reload_settings", lambda: Mock())
    monkeypatch.setattr("worker.tasks.get_sync_db", lambda: db)
    monkeypatch.setattr("worker.tasks.sync_get_job", lambda _db, _job_id: job)
    monkeypatch.setattr("worker.tasks.ImportPipeline", lambda *_args, **_kwargs: pipeline)
    monkeypatch.setattr("worker.tasks.sync_update_job", update)
    monkeypatch.setattr("worker.tasks.sync_record_attempt", record)

    run_import_job("job-fail")

    update.assert_called_once()
    assert update.call_args.kwargs["status"] == JobStatus.failed
    record.assert_called_once()
    assert record.call_args.kwargs["error_message"] == "pipeline exploded"
    db.close.assert_called_once()


def test_run_import_job_skips_record_when_cancelled(monkeypatch):
    db = Mock()
    job = Mock()
    job.status = JobStatus.cancelled
    pipeline = Mock()
    pipeline.run.side_effect = RuntimeError("cancelled race")
    update = Mock()
    monkeypatch.setattr("worker.tasks.reload_settings", lambda: Mock())
    monkeypatch.setattr("worker.tasks.get_sync_db", lambda: db)
    monkeypatch.setattr("worker.tasks.sync_get_job", lambda _db, _job_id: job)
    monkeypatch.setattr("worker.tasks.ImportPipeline", lambda *_args, **_kwargs: pipeline)
    monkeypatch.setattr("worker.tasks.sync_update_job", update)

    run_import_job("job-cancel")

    update.assert_not_called()
    db.close.assert_called_once()


def test_run_import_job_swallows_record_errors(monkeypatch):
    db = Mock()
    job = Mock()
    job.status = JobStatus.running
    pipeline = Mock()
    pipeline.run.side_effect = RuntimeError("pipeline exploded")
    monkeypatch.setattr("worker.tasks.reload_settings", lambda: Mock())
    monkeypatch.setattr("worker.tasks.get_sync_db", lambda: db)
    monkeypatch.setattr("worker.tasks.sync_get_job", lambda _db, _job_id: job)
    monkeypatch.setattr("worker.tasks.ImportPipeline", lambda *_args, **_kwargs: pipeline)
    monkeypatch.setattr("worker.tasks.sync_update_job", Mock(side_effect=RuntimeError("db down")))

    run_import_job("job-db-down")

    db.close.assert_called_once()
