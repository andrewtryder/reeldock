"""Tests for config loading: YAML merge and env override."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from app.config import Settings
from pydantic import ValidationError


def test_defaults(monkeypatch: pytest.MonkeyPatch):
    """Default settings are set correctly."""
    monkeypatch.delenv("ALLOW_PLAYLISTS", raising=False)
    monkeypatch.delenv("ALLOW_CHANNELS", raising=False)
    monkeypatch.delenv("MAX_PLAYLIST_ENTRIES", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    s = Settings()
    assert s.app_host == "0.0.0.0"
    assert s.app_port == 8080
    assert s.allow_playlists is False
    assert s.allow_channels is False
    assert s.max_playlist_entries == 100
    assert s.dry_run is False
    assert s.retry_max == 3
    assert s.ytdlp_audio_format == "m4a"
    assert s.collision_mode == "append_id"


def test_env_override(monkeypatch: pytest.MonkeyPatch):
    """Environment variables override defaults."""
    monkeypatch.setenv("APP_PORT", "9090")
    monkeypatch.setenv("ALLOW_PLAYLISTS", "true")
    s = Settings()
    assert s.app_port == 9090
    assert s.allow_playlists is True


def test_ytdlp_extra_args_from_env(monkeypatch: pytest.MonkeyPatch):
    """Space-separated YTDLP_EXTRA_ARGS string is parsed to list."""
    monkeypatch.setenv("YTDLP_EXTRA_ARGS", "--verbose --no-warnings")
    s = Settings()
    assert s.ytdlp_extra_args == ["--verbose", "--no-warnings"]


def test_retry_intervals_from_env(monkeypatch: pytest.MonkeyPatch):
    """Comma-separated RETRY_INTERVAL_SECONDS is parsed to int list."""
    monkeypatch.setenv("RETRY_INTERVAL_SECONDS", "30,120,600")
    s = Settings()
    assert s.retry_interval_seconds == [30, 120, 600]


def test_invalid_collision_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COLLISION_MODE", "bogus")
    with pytest.raises(ValidationError):
        Settings()


def test_abs_base_url_from_env_rejects_unsafe_schemes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ABS_BASE_URL", "javascript:alert(1)")
    with pytest.raises(ValidationError):
        Settings()


def test_abs_base_url_from_env_accepts_http(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ABS_BASE_URL", "http://abs:13378")
    s = Settings()
    assert s.abs_base_url == "http://abs:13378"


def test_yaml_loading_returns_empty_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "nonexistent.yaml"))
    import app.config as cfg_module

    saved = cfg_module._CONFIG_YAML_PATH
    cfg_module._CONFIG_YAML_PATH = tmp_path / "nonexistent.yaml"
    try:
        result = cfg_module._load_yaml()
        assert result == {}
    finally:
        cfg_module._CONFIG_YAML_PATH = saved


def test_yaml_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = {
        "app": {"port": 7777, "auth_enabled": True},
        "paths": {"output_root": "/tmp/test-output"},
        "download": {"allow_playlists": True, "audio_format": "opus"},
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(config))

    import app.config as cfg_module

    saved = cfg_module._CONFIG_YAML_PATH
    cfg_module._CONFIG_YAML_PATH = cfg_file
    try:
        flat = cfg_module._load_yaml()
    finally:
        cfg_module._CONFIG_YAML_PATH = saved

    assert flat.get("APP_PORT") == 7777
    assert flat.get("AUTH_ENABLED") is True
    assert flat.get("OUTPUT_ROOT") == "/tmp/test-output"
    assert flat.get("ALLOW_PLAYLISTS") is True
    assert flat.get("YTDLP_AUDIO_FORMAT") == "opus"


def test_abs_configured_property(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ABS_BASE_URL", "http://abs:13378")
    monkeypatch.setenv("ABS_API_TOKEN", "mytoken")
    monkeypatch.setenv("ABS_LIBRARY_ID", "lib123")
    s = Settings()
    assert s.abs_configured is True


def test_abs_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ABS_BASE_URL", raising=False)
    monkeypatch.delenv("ABS_API_TOKEN", raising=False)
    monkeypatch.delenv("ABS_LIBRARY_ID", raising=False)
    s = Settings()
    assert s.abs_configured is False


def test_sync_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:////data/app.db")
    s = Settings()
    assert "aiosqlite" not in s.sync_database_url
    assert s.sync_database_url == "sqlite:////data/app.db"


def test_collect_pinned_sources_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OUTPUT_ROOT", "/env/output")
    import app.config as cfg_module

    cfg_module._settings = None
    pinned = cfg_module._collect_pinned_sources()
    assert pinned["OUTPUT_ROOT"] == "env"


def test_db_override_applies_when_not_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.delenv("OUTPUT_ROOT", raising=False)
    monkeypatch.setattr(cfg_module, "_get_default_data_dir", lambda: data_dir)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())

    cfg_module._settings = None
    cfg_module._pinned_sources = {}
    cfg_module._db_overrides = {}
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None

    asyncio.run(init_db())

    custom = data_dir / "db_output"
    custom.mkdir()
    save_settings({"output_root": str(custom)})
    settings = reload_settings()
    assert settings.output_root == custom


def test_env_blocks_db_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OUTPUT_ROOT", "/env/output")
    monkeypatch.setattr(cfg_module, "_get_default_data_dir", lambda: data_dir)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())

    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None

    asyncio.run(init_db())

    save_settings({"output_root": "/db/output"})
    settings = reload_settings()
    assert settings.output_root == Path("/env/output")


def test_yaml_blocks_db_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"paths": {"output_root": "/yaml/output"}}))

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.delenv("OUTPUT_ROOT", raising=False)
    monkeypatch.setattr(cfg_module, "_get_default_data_dir", lambda: data_dir)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    monkeypatch.setattr(cfg_module, "_CONFIG_YAML_PATH", cfg_file)

    cfg_module._settings = None
    cfg_module._pinned_sources = {}
    cfg_module._db_overrides = {}
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None

    pinned = cfg_module._collect_pinned_sources()
    assert pinned["OUTPUT_ROOT"] == "yaml"

    asyncio.run(init_db())

    save_settings({"output_root": "/db/output"})
    settings = reload_settings()
    assert settings.output_root == Path("/yaml/output")


def test_get_settings_does_not_mutate_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.config as cfg_module

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"download": {"allow_playlists": True}}))
    monkeypatch.setattr(cfg_module, "_CONFIG_YAML_PATH", cfg_file)
    monkeypatch.delenv("ALLOW_PLAYLISTS", raising=False)
    before = dict(os.environ)
    cfg_module._settings = None
    settings = cfg_module.get_settings()
    assert settings.allow_playlists is True
    assert "ALLOW_PLAYLISTS" not in os.environ or os.environ.get("ALLOW_PLAYLISTS") == before.get(
        "ALLOW_PLAYLISTS"
    )


def test_blank_env_does_not_pin_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_PASSWORD", "")
    monkeypatch.setenv("REELDOCK_CONFIG_MODE", "ui")
    import app.config as cfg_module

    cfg_module._settings = None
    pinned = cfg_module._collect_pinned_sources()
    assert "AUTH_PASSWORD" not in pinned


def test_ui_mode_db_overrides_env_operational(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'mode.db'}")
    monkeypatch.setenv("REELDOCK_CONFIG_MODE", "ui")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())
    save_settings({"dry_run": "true"})
    assert reload_settings().dry_run is True


def test_locked_mode_env_wins_over_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'locked.db'}")
    monkeypatch.setenv("REELDOCK_CONFIG_MODE", "locked")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())
    save_settings({"dry_run": "true"})
    assert reload_settings().dry_run is False
