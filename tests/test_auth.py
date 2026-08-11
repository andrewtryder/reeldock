"""Tests for HTTP Basic Auth and auth configuration guards."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "test-auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.delenv("EXTENSION_API_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    import app.config as cfg_module
    import app.db as db_module

    cfg_module._settings = None
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_auth_enabled_rejects_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "secret")

    import app.config as cfg_module

    cfg_module._settings = None

    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 401
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code in {200, 503}


def test_auth_enabled_accepts_valid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "secret")

    import app.config as cfg_module

    cfg_module._settings = None

    with TestClient(create_app()) as client:
        response = client.get("/", headers=_basic("admin", "secret"))
        assert response.status_code == 200


def test_auth_enabled_rejects_wrong_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "secret")

    import app.config as cfg_module

    cfg_module._settings = None

    with TestClient(create_app()) as client:
        assert client.get("/", headers=_basic("admin", "wrong")).status_code == 401


def test_auth_enabled_without_credentials_fails_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    import app.config as cfg_module

    cfg_module._settings = None
    with pytest.raises(ValidationError, match="AUTH_USERNAME"):
        cfg_module.Settings(_env_file=None)


def test_extension_api_enabled_without_token_fails_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.delenv("EXTENSION_API_TOKEN", raising=False)

    import app.config as cfg_module

    cfg_module._settings = None
    with pytest.raises(ValidationError, match="EXTENSION_API_TOKEN"):
        cfg_module.Settings(_env_file=None)


def test_basic_auth_and_extension_token_coexist(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTH_ENABLED and EXTENSION_API_ENABLED can run together.

    ``/`` and Web UI APIs stay behind Basic. Extension routes accept Bearer
    only. Health stays open.
    """
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "secret")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "test-token-12345")

    import app.config as cfg_module

    cfg_module._settings = None

    bearer = {"Authorization": "Bearer test-token-12345"}
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 401
        assert client.get("/health").status_code == 200
        assert client.get("/api/extension/status").status_code == 401
        status = client.get("/api/extension/status", headers=bearer)
        assert status.status_code == 200
        assert status.json()["ok"] is True
        assert client.get("/api/folders").status_code == 401
        assert client.get("/api/folders", headers=bearer).status_code == 401
        # HTTP on /api/ws/ is not a WebSocket upgrade, so Basic still applies.
        assert client.get("/api/ws/jobs/example").status_code == 401
