"""Coverage for Redis/RQ helpers in app.queue."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import app.queue as queue_mod


def _reset_singletons() -> None:
    queue_mod._redis_conn = None
    queue_mod._queue = None


def test_get_redis_reuses_connection(monkeypatch):
    _reset_singletons()
    fake_redis = object()
    monkeypatch.setattr(queue_mod.Redis, "from_url", staticmethod(lambda _url: fake_redis))
    monkeypatch.setattr(
        queue_mod, "get_settings", lambda: SimpleNamespace(redis_url="redis://localhost:6379/0")
    )

    assert queue_mod.get_redis() is fake_redis
    assert queue_mod.get_redis() is fake_redis


def test_get_queue_reuses_queue(monkeypatch):
    _reset_singletons()
    fake_queue = object()
    monkeypatch.setattr(queue_mod, "get_redis", lambda: object())
    monkeypatch.setattr(
        queue_mod,
        "get_settings",
        lambda: SimpleNamespace(job_timeout_seconds=120),
    )
    monkeypatch.setattr(
        queue_mod,
        "Queue",
        lambda name, connection, default_timeout=None: fake_queue,
    )

    assert queue_mod.get_queue() is fake_queue
    assert queue_mod.get_queue() is fake_queue


def test_build_rq_retry_disabled(monkeypatch):
    monkeypatch.setattr(
        queue_mod,
        "get_settings",
        lambda: SimpleNamespace(retry_max=0, retry_interval_seconds=[10]),
    )
    assert queue_mod._build_rq_retry() is None


def test_build_rq_retry_enabled(monkeypatch):
    monkeypatch.setattr(
        queue_mod,
        "get_settings",
        lambda: SimpleNamespace(retry_max=3, retry_interval_seconds=[5, 15]),
    )
    retry = queue_mod._build_rq_retry()
    assert retry is not None
    assert retry.max == 3
    assert list(retry.intervals) == [5, 15, 15]


def test_build_rq_retry_without_rq(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rq":
            raise ImportError("no rq")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert queue_mod._build_rq_retry() is None


def test_enqueue_job_task_returns_rq_id(monkeypatch):
    _reset_singletons()
    rq_job = Mock()
    rq_job.id = "rq-abc"
    fake_queue = Mock()
    fake_queue.enqueue.return_value = rq_job
    monkeypatch.setattr(queue_mod, "get_queue", lambda: fake_queue)
    monkeypatch.setattr(queue_mod, "_build_rq_retry", lambda: None)
    monkeypatch.setattr(queue_mod, "get_settings", lambda: SimpleNamespace(job_timeout_seconds=120))

    assert queue_mod.enqueue_job_task("job-9") == "rq-abc"
    fake_queue.enqueue.assert_called_once()
    assert fake_queue.enqueue.call_args.args[1] == "job-9"
