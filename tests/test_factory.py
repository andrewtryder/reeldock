"""Tests for application factory startup behaviour."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app.factory import _fallback_ui_version, create_app
from app.routes.pages import templates
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "test-factory.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import app.config as cfg_module
    import app.db as db_module

    cfg_module._settings = None
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


def test_fallback_ui_version_prefixes_and_preserves_v() -> None:
    assert _fallback_ui_version("1.10.2") == "v1.10.2"
    assert _fallback_ui_version("v1.10.2") == "v1.10.2"


def test_package_version_1_10_2_renders_v1_10_2() -> None:
    with (
        patch("app.factory._package_version", return_value="1.10.2"),
        TestClient(create_app()) as client,
    ):
        assert client.app.state.ui_version == "v1.10.2"
        assert templates.env.globals["app_ui_version"] == "v1.10.2"
        response = client.get("/")
        assert response.status_code == 200
        assert "reeldock v1.10.2" in response.text


def test_factory_does_not_import_httpx() -> None:
    import app.factory as factory_module

    assert not hasattr(factory_module, "httpx")


def test_browser_extension_release_name_cannot_affect_ui_version() -> None:
    with (
        patch("app.factory._package_version", return_value="1.10.2"),
        TestClient(create_app()) as client,
    ):
        assert client.app.state.ui_version == "v1.10.2"
        assert client.app.state.ui_version != "browser-extension-v1.10.1"
        assert "browser-extension" not in client.app.state.ui_version
