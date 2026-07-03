"""Tests for /health and /ready endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "test-readiness.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")

    import app.config as cfg_module
    import app.db as db_module

    cfg_module._settings = None
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _writable_settings(tmp_path: Path) -> SimpleNamespace:
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    return SimpleNamespace(output_root=output_root, work_dir=work_dir)


def test_health_unchanged(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_paths_writable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import app.preflight as preflight_module

    settings = _writable_settings(tmp_path)
    monkeypatch.setattr(
        preflight_module,
        "check_required_paths",
        lambda settings=None: preflight_module.check_required_paths(settings),
    )
    monkeypatch.setattr(preflight_module, "get_settings", lambda: settings)

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["output_root"]["ok"] is True
    assert body["checks"]["work_dir"]["ok"] is True


def test_ready_returns_503_when_output_not_writable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import app.preflight as preflight_module

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    settings = SimpleNamespace(
        output_root=tmp_path / "missing-podcasts",
        work_dir=work_dir,
    )
    monkeypatch.setattr(
        preflight_module,
        "check_required_paths",
        lambda settings=None: preflight_module.check_required_paths(settings),
    )
    monkeypatch.setattr(preflight_module, "get_settings", lambda: settings)

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["output_root"]["ok"] is False
    assert "error" in body["checks"]["output_root"]


def test_ready_bypasses_basic_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import app.config as cfg_module
    import app.preflight as preflight_module

    settings = _writable_settings(tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "secret")
    cfg_module._settings = None

    monkeypatch.setattr(
        preflight_module,
        "check_required_paths",
        lambda settings=None: preflight_module.check_required_paths(settings),
    )
    monkeypatch.setattr(preflight_module, "get_settings", lambda: settings)

    with TestClient(create_app()) as auth_client:
        protected = auth_client.get("/")
        assert protected.status_code == 401

        ready = auth_client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
