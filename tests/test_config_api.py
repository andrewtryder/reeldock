"""Tests for public JSON config/preview API routes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "test-config-api.db"
    output_root = tmp_path / "podcasts"
    work_dir = tmp_path / "work"
    output_root.mkdir()
    work_dir.mkdir()

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("WORK_DIR", str(work_dir))
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.delenv("EXTENSION_API_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "false")

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


def test_api_config_returns_legacy_shape(client: TestClient):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "output_root",
        "allow_playlists",
        "allow_channels",
        "abs_configured",
        "abs_scan_after_success",
        "dry_run",
        "max_concurrent_jobs",
    }
    assert body["max_concurrent_jobs"] == 1


def test_api_folders_returns_list(client: TestClient):
    response = client.get("/api/folders")
    assert response.status_code == 200
    body = response.json()
    assert "folders" in body
    assert isinstance(body["folders"], list)


def test_api_preview_rejects_invalid_url(client: TestClient):
    response = client.post("/api/preview", data={"url": "not-a-valid-url"})
    assert response.status_code == 400
