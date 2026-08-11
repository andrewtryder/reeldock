"""Tests for browser extension API endpoints."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.main import create_app
from app.services.ytdlp import YtDlpService
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Use an isolated SQLite DB per test and clear cached engines."""
    db_path = tmp_path / "test-extension-api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import app.db as db_module

    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Create a test client for the FastAPI app."""
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "")
    import app.config as cfg_module

    cfg_module._settings = None
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def extension_enabled_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Create a test client with extension API enabled and a required token."""
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "test-token-12345")
    # Need to clear the settings cache after setting env vars
    import app.config as cfg_module

    cfg_module._settings = None
    with TestClient(create_app()) as test_client:
        yield test_client


EXT_AUTH = {"Authorization": "Bearer test-token-12345"}


@pytest.fixture
def mocked_ytdlp(monkeypatch):
    """Mock YtDlpService methods for tests."""

    mock_svc = Mock(spec=YtDlpService)
    mock_svc.validate_url.return_value = Mock(valid=True)
    mock_svc.run_preview.return_value = Mock(
        id="test123",
        title="Test Video",
        uploader="Test Uploader",
        uploader_id="user123",
        channel="Test Channel",
        channel_id="channel123",
        duration=180,
        upload_date="20240101",
        thumbnail="https://example.com/thumb.jpg",
        chapter_count=3,
        webpage_url="https://youtube.com/watch?v=test123",
    )

    # Patch where extension routes import these symbols.
    def _factory(*args, **kwargs):
        return mock_svc

    monkeypatch.setattr("app.routes.extension.YtDlpService", _factory)
    monkeypatch.setattr("app.services.ytdlp.YtDlpService", _factory)
    yield mock_svc


@pytest.fixture
def mocked_enqueue(monkeypatch):
    """Mock Redis enqueue so queue/cancel/retry tests do not need Redis."""
    monkeypatch.setattr("app.services.jobs.enqueue_job_task", lambda job_id: "rq-job-123")


@pytest.fixture
def mocked_queue(monkeypatch):
    """Mock enqueue_job_task and update_job_status for tests."""
    with monkeypatch.context() as m:

        async def _noop(*a, **kw):
            return None

        # Patch where extension routes import these symbols.
        m.setattr("app.services.jobs.enqueue_job_task", lambda job_id: "rq-job-123")
        m.setattr("app.services.jobs.update_job_status", _noop)
        yield m


def _db_path() -> Path:
    db_url = os.environ["DATABASE_URL"]
    prefix = "sqlite+aiosqlite:///"
    if not db_url.startswith(prefix):
        raise AssertionError(f"Unexpected DATABASE_URL in test: {db_url}")
    return Path(db_url.removeprefix(prefix))


def _seed_imported_video(video_id: str) -> None:
    """Insert an imported video row directly into the sqlite test database."""
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO imported_videos (video_id, job_id, source_url, source_title)
            VALUES (?, ?, ?, ?)
            """,
            (video_id, "existing-job", "https://www.youtube.com/watch?v=test123", "Old Title"),
        )
        conn.commit()


def _mark_job_status(job_id: str, status: str) -> None:
    from app.db import get_sync_session_factory
    from app.models import Job, JobStatus

    with get_sync_session_factory()() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus(status)
        session.commit()


def _mark_job_succeeded(job_id: str) -> None:
    """Mark a job terminal so the WebSocket handler exits without polling."""
    _mark_job_status(job_id, "succeeded")


def _get_job_row(job_id: str):
    from app.db import get_sync_session_factory
    from app.models import Job

    with get_sync_session_factory()() as session:
        job = session.get(Job, job_id)
        assert job is not None
        session.expunge(job)
        return job


def _queue_job(client: TestClient, extra: dict | None = None) -> str:
    payload = {
        "url": "https://www.youtube.com/watch?v=test123",
        "destination_folder": "",
        "output_title": "",
        "embed_metadata": True,
        "embed_thumbnail": True,
        "embed_chapters": True,
        "trigger_abs_scan": False,
    }
    if extra:
        payload.update(extra)
    response = client.post("/api/extension/queue", headers=EXT_AUTH, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


# ---------------------------------------------------------------------------
# Extension Status Endpoint Tests
# ---------------------------------------------------------------------------


def test_extension_status_disabled_by_default(client):
    """Test that extension API returns 404 when disabled."""
    response = client.get("/api/extension/status")
    assert response.status_code == 404
    assert "Extension API not enabled" in response.text


def test_extension_status_enabled_requires_token(extension_enabled_client):
    """Token is always required when the extension API is enabled."""
    response = extension_enabled_client.get("/api/extension/status")
    assert response.status_code == 401


def test_extension_status_enabled_with_token(extension_enabled_client):
    """Test extension status when enabled and token required."""
    response = extension_enabled_client.get("/api/extension/status")
    assert response.status_code == 401


def test_extension_status_with_bearer_token(extension_enabled_client):
    """Test extension status with Bearer token."""
    response = extension_enabled_client.get(
        "/api/extension/status",
        headers={"Authorization": "Bearer test-token-12345"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["auth_required"] is True
    assert data["app"] == "reeldock"
    assert data["api_version"] == 1
    assert data["supports"] == {
        "destinations": True,
        "quality_presets": True,
        "sponsorblock": True,
        "cancel": True,
        "retry": True,
    }


def test_extension_status_with_wrong_token(extension_enabled_client):
    """Test extension status with wrong token rejects access."""
    response = extension_enabled_client.get(
        "/api/extension/status",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert "Invalid extension API token" in response.text


def test_extension_status_with_xtabs_token(extension_enabled_client):
    """Test extension status with X-REELDOCK-Token header."""
    response = extension_enabled_client.get(
        "/api/extension/status",
        headers={"X-REELDOCK-Token": "test-token-12345"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Extension Queue Endpoint Tests
# ---------------------------------------------------------------------------


def test_extension_queue_disabled_by_default(client):
    """Test extension queue returns 404 when API is disabled."""
    response = client.post(
        "/api/extension/queue",
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 404


def test_extension_queue_requires_token(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Queue rejects requests when the required token is missing."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 401


def test_extension_queue_enabled_with_token(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue with valid bearer token."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={"Authorization": "Bearer test-token-12345"},
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "job_id" in data
    assert "rq_job_id" in data
    assert data["status"] == "queued"


def test_extension_queue_with_xtabs_token(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue with X-REELDOCK-Token header."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={"X-REELDOCK-Token": "test-token-12345"},
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "job_id" in data
    assert "rq_job_id" in data


def test_extension_queue_wrong_token(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue with wrong token is rejected."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={"Authorization": "Bearer wrong-token"},
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 401
    assert "Invalid extension API token" in response.text


def test_extension_queue_invalid_url(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue with invalid URL returns 400."""
    from app.services.ytdlp import UrlValidationResult

    mocked_ytdlp.validate_url.return_value = UrlValidationResult(valid=False, error="URL is empty")

    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "url": "https://example.com/not-youtube",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 400
    assert "URL is empty" in response.text


def test_extension_queue_metadata_failure(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue when metadata fetch fails returns 422."""
    mocked_ytdlp.run_preview.side_effect = Exception("yt-dlp failed")

    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 422
    assert "yt-dlp failed" in response.text


def test_extension_queue_rejects_already_imported(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    """Queue endpoint should fail early for already imported video ids."""
    _seed_imported_video("test123")

    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 409
    assert "already been imported" in response.text


def test_extension_queue_allows_reimport_with_flag(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    """Queue endpoint should allow duplicates when allow_reimport=true."""
    _seed_imported_video("test123")

    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
            "allow_reimport": True,
        },
    )
    assert response.status_code == 201


def test_extension_queue_json_parsing_error(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue with invalid JSON returns 400."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={**EXT_AUTH, "Content-Type": "application/json"},
        data="invalid json",
    )
    assert response.status_code == 400
    assert "Invalid JSON body" in response.text


def test_extension_queue_no_url_field(extension_enabled_client, mocked_ytdlp, mocked_queue):
    """Test extension queue without URL field returns 400."""
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert response.status_code == 400
    assert "URL is required" in response.text


# ---------------------------------------------------------------------------
# Extension WebSocket Auth Tests
# ---------------------------------------------------------------------------


def test_extension_websocket_accepts_query_token(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    """WebSocket auth should accept `?token=` for browser extension clients."""
    queue_response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={"Authorization": "Bearer test-token-12345"},
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert queue_response.status_code == 201
    job_id = queue_response.json()["job_id"]
    # Terminal before connect so the handler sends one update and returns
    # without entering the poll loop (avoids Starlette TestClient hangs on CI).
    _mark_job_succeeded(job_id)

    with extension_enabled_client.websocket_connect(
        f"/api/ws/jobs/{job_id}?token=test-token-12345"
    ) as websocket:
        payload = websocket.receive_json()
        assert payload["type"] == "job_update"
        assert payload["job"]["id"] == job_id
        assert payload["job"]["status"] == "succeeded"
        # Drain close frame so the context manager does not wait on the portal.
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_extension_websocket_rejects_wrong_query_token(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    """WebSocket auth should reject invalid query tokens."""
    queue_response = extension_enabled_client.post(
        "/api/extension/queue",
        headers={"Authorization": "Bearer test-token-12345"},
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "destination_folder": "",
            "output_title": "",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "trigger_abs_scan": False,
        },
    )
    assert queue_response.status_code == 201
    job_id = queue_response.json()["job_id"]

    with extension_enabled_client.websocket_connect(
        f"/api/ws/jobs/{job_id}?token=wrong-token"
    ) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


def test_extension_api_disabled_in_settings(monkeypatch: pytest.MonkeyPatch):
    """Test that extension API disabled setting is reflected in status."""
    import app.config as cfg_module

    cfg_module._settings = None
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "")
    client = TestClient(create_app())
    response = client.get("/api/extension/status")
    assert response.status_code == 404
    assert "Extension API not enabled" in response.text


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------


def test_destinations_return_404_when_disabled(client):
    response = client.get("/api/extension/destinations")
    assert response.status_code == 404


def test_extension_destinations_requires_token(extension_enabled_client):
    assert extension_enabled_client.get("/api/extension/destinations").status_code == 401


def test_extension_destinations_empty(tmp_path, monkeypatch):
    output_root = tmp_path / "empty-library"
    output_root.mkdir()
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "test-token-12345")
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.delenv("DEFAULT_DESTINATION_FOLDER", raising=False)
    import app.config as cfg_module

    cfg_module._settings = None
    with TestClient(create_app()) as dest_client:
        response = dest_client.get("/api/extension/destinations", headers=EXT_AUTH)
    assert response.status_code == 200
    assert response.json() == {"default": "", "folders": []}


def test_extension_destinations_multiple_and_default(tmp_path, monkeypatch):
    output_root = tmp_path / "library"
    output_root.mkdir()
    (output_root / "Lectures").mkdir()
    (output_root / "Theology").mkdir()
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "test-token-12345")
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("DEFAULT_DESTINATION_FOLDER", "Theology")
    import app.config as cfg_module

    cfg_module._settings = None
    with TestClient(create_app()) as dest_client:
        response = dest_client.get("/api/extension/destinations", headers=EXT_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["default"] == "Theology"
    assert body["folders"] == ["Lectures", "Theology"]
    assert all(not name.startswith("/") and ".." not in name for name in body["folders"])


def test_extension_destinations_default_missing_falls_back_to_root(tmp_path, monkeypatch):
    output_root = tmp_path / "library"
    output_root.mkdir()
    (output_root / "Lectures").mkdir()
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "test-token-12345")
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("DEFAULT_DESTINATION_FOLDER", "Theology")
    import app.config as cfg_module

    cfg_module._settings = None
    with TestClient(create_app()) as dest_client:
        response = dest_client.get("/api/extension/destinations", headers=EXT_AUTH)
    assert response.status_code == 200
    assert response.json() == {"default": "", "folders": ["Lectures"]}


def test_extension_destinations_strips_traversal_names(extension_enabled_client, monkeypatch):
    monkeypatch.setattr(
        "app.services.filesystem.FilesystemService.list_folders",
        lambda self, recursive=False: ["Theology", "../etc", "/var/media", "Lectures"],
    )
    response = extension_enabled_client.get("/api/extension/destinations", headers=EXT_AUTH)
    assert response.status_code == 200
    assert response.json()["folders"] == ["Theology", "Lectures"]
    assert response.json()["default"] == ""


# ---------------------------------------------------------------------------
# Queue quality / SponsorBlock
# ---------------------------------------------------------------------------


def test_extension_queue_maps_quality_and_sponsorblock(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    job_id = _queue_job(
        extension_enabled_client,
        {"quality": "high", "sponsorblock_remove": True},
    )
    job = _get_job_row(job_id)
    assert job.audio_quality == "192K"
    assert job.sponsorblock_remove is True


def test_extension_queue_default_quality_is_standard(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    job_id = _queue_job(extension_enabled_client)
    job = _get_job_row(job_id)
    assert job.audio_quality == "128K"
    assert job.sponsorblock_remove is False


def test_extension_queue_rejects_unknown_quality(
    extension_enabled_client, mocked_ytdlp, mocked_queue
):
    response = extension_enabled_client.post(
        "/api/extension/queue",
        headers=EXT_AUTH,
        json={
            "url": "https://www.youtube.com/watch?v=test123",
            "quality": "ultra",
        },
    )
    assert response.status_code == 400
    assert "Unknown quality" in response.text


def test_extension_queue_maps_best_quality(extension_enabled_client, mocked_ytdlp, mocked_queue):
    job_id = _queue_job(extension_enabled_client, {"quality": "best"})
    assert _get_job_row(job_id).audio_quality == "0"


# ---------------------------------------------------------------------------
# Job GET / cancel / retry
# ---------------------------------------------------------------------------


def test_extension_get_job_happy(extension_enabled_client, mocked_ytdlp, mocked_queue):
    job_id = _queue_job(extension_enabled_client, {"output_title": "My Book"})
    response = extension_enabled_client.get(f"/api/extension/jobs/{job_id}", headers=EXT_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "queued"
    assert body["title"] == "My Book"
    assert body["uploader"] == "Test Uploader"
    assert body["job_url"] == f"/jobs/{job_id}"
    assert "final_output_path" not in body
    assert "log_file_path" not in body
    assert "rq_job_id" not in body
    assert "work_dir" not in body


def test_extension_get_job_404(extension_enabled_client):
    response = extension_enabled_client.get("/api/extension/jobs/missing-id", headers=EXT_AUTH)
    assert response.status_code == 404


def test_extension_get_job_bad_token(extension_enabled_client, mocked_ytdlp, mocked_queue):
    job_id = _queue_job(extension_enabled_client)
    response = extension_enabled_client.get(
        f"/api/extension/jobs/{job_id}",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_extension_cancel_job_happy(extension_enabled_client, mocked_ytdlp, mocked_enqueue):
    job_id = _queue_job(extension_enabled_client)
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/cancel", headers=EXT_AUTH
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _get_job_row(job_id).status == "cancelled"


def test_extension_cancel_job_409_when_terminal(
    extension_enabled_client, mocked_ytdlp, mocked_enqueue
):
    job_id = _queue_job(extension_enabled_client)
    _mark_job_succeeded(job_id)
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/cancel", headers=EXT_AUTH
    )
    assert response.status_code == 409


def test_extension_cancel_job_404(extension_enabled_client):
    response = extension_enabled_client.post(
        "/api/extension/jobs/missing-id/cancel", headers=EXT_AUTH
    )
    assert response.status_code == 404


def test_extension_cancel_job_bad_token(extension_enabled_client, mocked_ytdlp, mocked_enqueue):
    job_id = _queue_job(extension_enabled_client)
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/cancel",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_extension_retry_job_happy(extension_enabled_client, mocked_ytdlp, monkeypatch):
    monkeypatch.setattr("app.services.jobs.enqueue_job_task", lambda _job_id: "rq-retry-1")
    job_id = _queue_job(extension_enabled_client)
    _mark_job_status(job_id, "failed")
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/retry", headers=EXT_AUTH
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["rq_job_id"] == "rq-retry-1"
    assert _get_job_row(job_id).status == "queued"


def test_retry_rejects_active_job_with_409(extension_enabled_client, mocked_ytdlp, mocked_enqueue):
    job_id = _queue_job(extension_enabled_client)
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/retry", headers=EXT_AUTH
    )
    assert response.status_code == 409


def test_extension_retry_job_404(extension_enabled_client):
    response = extension_enabled_client.post(
        "/api/extension/jobs/missing-id/retry", headers=EXT_AUTH
    )
    assert response.status_code == 404


def test_extension_retry_job_bad_token(extension_enabled_client, mocked_ytdlp, mocked_enqueue):
    job_id = _queue_job(extension_enabled_client)
    _mark_job_status(job_id, "failed")
    response = extension_enabled_client.post(
        f"/api/extension/jobs/{job_id}/retry",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_extension_job_routes_disabled_404(client):
    assert client.get("/api/extension/jobs/any").status_code == 404
    assert client.post("/api/extension/jobs/any/cancel").status_code == 404
    assert client.post("/api/extension/jobs/any/retry").status_code == 404
