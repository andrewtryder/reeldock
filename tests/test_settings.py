from __future__ import annotations

import re
from pathlib import Path

import app.config as config_module
import app.db as db_module
import pytest
from app.config import get_setting_sources, reload_settings, save_settings
from app.factory import create_app
from fastapi.testclient import TestClient
from sqlalchemy import select

_LOUDNESS_FORM_FIELDS = {
    "loudness_normalize": "",
    "loudness_target_lufs": "-16",
    "loudness_audio_bitrate": "192k",
}


def _reset_runtime_state() -> None:
    config_module._settings = None
    config_module._pinned_sources = {}
    config_module._db_overrides = {}
    config_module._bootstrap_values = {}
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


@pytest.fixture
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated data directory and SQLite database for settings tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.delenv("EXTENSION_API_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("ALLOW_PLAYLISTS", raising=False)
    monkeypatch.delenv("ALLOW_CHANNELS", raising=False)
    monkeypatch.delenv("MAX_PLAYLIST_ENTRIES", raising=False)
    monkeypatch.delenv("ABS_SCAN_AFTER_SUCCESS", raising=False)
    monkeypatch.delenv("YTDLP_EXTRA_ARGS", raising=False)
    monkeypatch.delenv("FFMPEG_EXTRA_ARGS", raising=False)
    monkeypatch.delenv("COLLISION_MODE", raising=False)
    monkeypatch.delenv("FILENAME_TEMPLATE", raising=False)
    monkeypatch.delenv("OUTPUT_EXTENSION", raising=False)
    monkeypatch.setattr(config_module, "_get_default_data_dir", lambda: data_dir)
    monkeypatch.setattr(config_module, "_parse_dotenv_keys", lambda: set())
    _reset_runtime_state()

    import asyncio

    from app.db import init_db

    asyncio.run(init_db())
    reload_settings()
    yield data_dir
    _reset_runtime_state()


def test_save_and_load_custom_settings(settings_env: Path):
    s1 = reload_settings()
    assert s1.output_root == Path("/media/podcasts")

    custom_path = settings_env / "my_custom_podcasts"
    custom_path.mkdir()
    save_settings(
        {
            "output_root": str(custom_path),
            "dry_run": "true",
            "allow_playlists": "true",
            "allow_channels": "true",
            "abs_scan_after_success": "true",
        }
    )

    s2 = reload_settings()
    assert s2.output_root == custom_path
    assert s2.dry_run is True
    assert s2.allow_playlists is True
    assert s2.allow_channels is True
    assert s2.abs_scan_after_success is True

    from app.db import get_sync_session_factory
    from app.models import AppSetting

    with get_sync_session_factory()() as session:
        rows = {row.key: row.value for row in session.scalars(select(AppSetting)).all()}
    assert rows["output_root"] == str(custom_path)
    assert rows["dry_run"] == "true"


def _csrf(client: TestClient) -> str:
    html = client.get("/settings").text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "csrf_token missing from settings page"
    return match.group(1)


def test_get_settings_page(settings_env: Path):
    with TestClient(create_app()) as client:
        response = client.get("/settings")
        assert response.status_code == 200
        assert "Settings" in response.text
        assert "Audiobook Library Path" in response.text
        assert "/media/podcasts" in response.text


def test_post_settings_valid(settings_env: Path, tmp_path: Path):
    with TestClient(create_app()) as client:
        valid_path = tmp_path / "new_output"
        response = client.post(
            "/settings",
            data={
                "csrf_token": _csrf(client),
                "output_root": str(valid_path),
                "dry_run": "on",
                "allow_playlists": "on",
                "allow_channels": "on",
                "abs_scan_after_success": "on",
                "collision_mode": "skip",
                "cleanup_temp_on_success": "on",
                "cleanup_temp_on_failure": "on",
                "job_timeout_seconds": "7200",
                "retry_max": "2",
                "retry_interval_seconds": "30,120",
                "max_playlist_entries": "50",
                "output_extension": "m4b",
                "filename_template": "{title}.m4b",
                "allowed_domains": "youtube.com,youtu.be",
                "ytdlp_extra_args": "--verbose",
                "ffmpeg_extra_args": "",
                "cookies_file": "",
                "default_destination_folder": "",
                **_LOUDNESS_FORM_FIELDS,
            },
        )
        assert response.status_code == 200
        assert "Settings saved successfully" in response.text
        assert str(valid_path) in response.text

    settings = reload_settings()
    assert settings.output_root == valid_path
    assert settings.dry_run is True
    assert settings.collision_mode == "skip"
    assert settings.retry_max == 2
    assert settings.max_playlist_entries == 50


def test_post_settings_relative(settings_env: Path):
    with TestClient(create_app()) as client:
        response = client.post(
            "/settings",
            data={
                "csrf_token": _csrf(client),
                "output_root": "some/relative/path",
                "collision_mode": "append_id",
                "job_timeout_seconds": "10800",
                "retry_max": "3",
                "retry_interval_seconds": "60,300,900",
                "max_playlist_entries": "100",
                "output_extension": "m4b",
                "filename_template": "{title}.m4b",
                "allowed_domains": "youtube.com",
                **_LOUDNESS_FORM_FIELDS,
            },
        )
        assert response.status_code == 400
        assert "absolute path" in response.text.lower()


def test_post_settings_non_writable(settings_env: Path):
    with TestClient(create_app()) as client:
        fake_file = settings_env / "not_a_dir"
        fake_file.touch()
        response = client.post(
            "/settings",
            data={
                "csrf_token": _csrf(client),
                "output_root": str(fake_file),
                "collision_mode": "append_id",
                "job_timeout_seconds": "10800",
                "retry_max": "3",
                "retry_interval_seconds": "60,300,900",
                "max_playlist_entries": "100",
                "output_extension": "m4b",
                "filename_template": "{title}.m4b",
                "allowed_domains": "youtube.com",
                **_LOUDNESS_FORM_FIELDS,
            },
        )
        assert response.status_code == 400
        assert "not writable" in response.text.lower()


def test_env_is_bootstrap_not_locked_in_ui_mode(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("REELDOCK_CONFIG_MODE", "ui")
    _reset_runtime_state()
    sources = get_setting_sources()
    assert sources["dry_run"]["locked"] is False
    assert sources["dry_run"]["label"] == "Deployment default"
    assert reload_settings().dry_run is True


def test_env_locks_setting_in_locked_mode(settings_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("REELDOCK_CONFIG_MODE", "locked")
    _reset_runtime_state()
    sources = get_setting_sources()
    assert sources["dry_run"]["locked"] is True
    assert sources["dry_run"]["source"] == "env"


def test_extra_args_reject_shell_injection(settings_env: Path):
    with TestClient(create_app()) as client:
        valid_path = settings_env / "output"
        valid_path.mkdir()
        response = client.post(
            "/settings",
            data={
                "csrf_token": _csrf(client),
                "output_root": str(valid_path),
                "ytdlp_extra_args": "--verbose; rm -rf /",
                "collision_mode": "append_id",
                "job_timeout_seconds": "10800",
                "retry_max": "3",
                "retry_interval_seconds": "60,300,900",
                "max_playlist_entries": "100",
                "output_extension": "m4b",
                "filename_template": "{title}.m4b",
                "allowed_domains": "youtube.com",
                **_LOUDNESS_FORM_FIELDS,
            },
        )
        assert response.status_code == 400
        assert "shell metacharacters" in response.text.lower()


def _base_form(output_root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    data = {
        "output_root": str(output_root),
        "collision_mode": "append_id",
        "job_timeout_seconds": "10800",
        "retry_max": "3",
        "retry_interval_seconds": "60,300,900",
        "max_playlist_entries": "100",
        "output_extension": "m4b",
        "filename_template": "{title}.m4b",
        "allowed_domains": "youtube.com",
        **_LOUDNESS_FORM_FIELDS,
    }
    if extra:
        data.update(extra)
    return data


def test_reset_endpoint_clears_override_and_does_not_rewrite(
    settings_env: Path,
) -> None:
    from app.db import get_sync_session_factory
    from app.models import AppSetting

    save_settings({"dry_run": "true"})
    assert reload_settings().dry_run is True

    with TestClient(create_app()) as client:
        html = client.get("/settings").text
        assert 'action="/settings/reset"' in html
        assert 'name="key" value="dry_run"' in html
        assert 'name="reset_dry_run"' not in html
        response = client.post(
            "/settings/reset",
            data={"csrf_token": _csrf(client), "key": "dry_run"},
        )
        assert response.status_code == 200
        assert "reset to the deployment/default" in response.text.lower()

    assert reload_settings().dry_run is False
    with get_sync_session_factory()() as session:
        assert session.get(AppSetting, "dry_run") is None


def test_enabling_auth_without_password_does_not_persist(settings_env: Path) -> None:
    from app.db import get_sync_session_factory
    from app.models import AppSetting

    with pytest.raises(ValueError, match="AUTH_ENABLED"):
        save_settings({"auth_enabled": "true", "auth_username": "admin"})

    with get_sync_session_factory()() as session:
        assert session.get(AppSetting, "auth_enabled") is None
    assert reload_settings().auth_enabled is False


def test_reset_password_rejected_while_auth_enabled(settings_env: Path) -> None:
    from app.db import get_sync_session_factory
    from app.models import AppSetting

    save_settings(
        {
            "auth_enabled": "true",
            "auth_username": "admin",
            "auth_password": "s3cret-pass",
        }
    )
    with TestClient(create_app()) as client:
        client.auth = ("admin", "s3cret-pass")
        response = client.post(
            "/settings/reset",
            data={"csrf_token": _csrf(client), "key": "auth_password"},
        )
        assert response.status_code == 400

    settings = reload_settings()
    assert settings.auth_enabled is True
    assert settings.auth_password == "s3cret-pass"
    with get_sync_session_factory()() as session:
        assert session.get(AppSetting, "auth_password") is not None


def test_password_confirm_mismatch_is_400(settings_env: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    with TestClient(create_app()) as client:
        response = client.post(
            "/settings",
            data=_base_form(
                output,
                {
                    "csrf_token": _csrf(client),
                    "auth_enabled": "on",
                    "auth_username": "admin",
                    "auth_password": "new-pass-1",
                    "auth_password_confirm": "new-pass-2",
                },
            ),
        )
        assert response.status_code == 400
        assert "confirmation do not match" in response.text.lower()
    assert reload_settings().auth_enabled is False


def test_password_confirm_match_saves(settings_env: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    with TestClient(create_app()) as client:
        response = client.post(
            "/settings",
            data=_base_form(
                output,
                {
                    "csrf_token": _csrf(client),
                    "auth_enabled": "on",
                    "auth_username": "admin",
                    "auth_password": "new-pass-1",
                    "auth_password_confirm": "new-pass-1",
                },
            ),
        )
        assert response.status_code == 200
    settings = reload_settings()
    assert settings.auth_enabled is True
    assert settings.auth_username == "admin"
    assert settings.auth_password == "new-pass-1"


def test_abs_test_does_not_persist(settings_env: Path, monkeypatch: pytest.MonkeyPatch):
    from unittest.mock import patch

    monkeypatch.setenv("ABS_BASE_URL", "http://stored-abs:13378")
    monkeypatch.setenv("ABS_API_TOKEN", "stored-token")
    monkeypatch.setenv("ABS_LIBRARY_ID", "stored-lib")
    reload_settings()
    libraries = [
        {"id": "lib-books", "name": "Audiobooks", "mediaType": "book"},
        {"id": "lib-pods", "name": "Podcasts", "mediaType": "podcast"},
    ]
    with TestClient(create_app()) as client:
        with patch(
            "app.services.audiobookshelf.AudiobookshelfClient.list_libraries",
            return_value=(libraries, None),
        ):
            response = client.post(
                "/settings/abs/test",
                data={
                    "csrf_token": _csrf(client),
                    "abs_base_url": "http://candidate-abs:13378",
                    "abs_api_token": "",
                    "abs_library_id": "gone-lib",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["libraries"][0]["mediaType"] == "book"
        assert "lib-books" in body["preferred_library_ids"]
        assert body["library_missing"] is True
        assert body["warning"]
        assert "stored-token" not in response.text

    settings = reload_settings()
    assert settings.abs_base_url == "http://stored-abs:13378"
    assert settings.abs_api_token == "stored-token"
    assert settings.abs_library_id == "stored-lib"
