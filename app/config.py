"""Application configuration.

Modes (REELDOCK_CONFIG_MODE):
  ui (default): DB/UI override > env/YAML bootstrap > defaults
  locked:       env/YAML > DB > defaults  (env/YAML-backed fields are read-only)

Blank environment/YAML values are treated as unset so Compose-injected empty
strings do not pin or lock UI-managed settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.path_checks import check_writable_directory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_YAML_PATH = Path(os.getenv("CONFIG_FILE", "/config/config.yaml"))


def _load_yaml() -> dict[str, Any]:
    """Load YAML config file if it exists, returning a flat env-style dict."""
    if not _CONFIG_YAML_PATH.exists():
        return {}

    with _CONFIG_YAML_PATH.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    flat: dict[str, Any] = {}

    # app section
    app = raw.get("app", {})
    flat.update(
        {
            "APP_HOST": app.get("host", None),
            "APP_PORT": app.get("port", None),
            "AUTH_ENABLED": app.get("auth_enabled", None),
            "AUTH_USERNAME": app.get("auth_username", None),
            "AUTH_PASSWORD": app.get("auth_password", None),
            "EXTENSION_PUBLIC_URL": app.get("extension_public_url", None),
        }
    )

    # paths section
    paths = raw.get("paths", {})
    flat.update(
        {
            "WORK_DIR": paths.get("work_dir", None),
            "ARCHIVE_FILE": paths.get("archive_file", None),
            "OUTPUT_ROOT": paths.get("output_root", None),
        }
    )

    # download section
    dl = raw.get("download", {})
    flat.update(
        {
            "ALLOW_PLAYLISTS": dl.get("allow_playlists", None),
            "ALLOW_CHANNELS": dl.get("allow_channels", None),
            "MAX_PLAYLIST_ENTRIES": dl.get("max_playlist_entries", None),
            "DEFAULT_DESTINATION_FOLDER": dl.get("default_destination_folder", None),
            "YTDLP_AUDIO_FORMAT": dl.get("audio_format", None),
            "YTDLP_AUDIO_QUALITY": dl.get("audio_quality", None),
            "YTDLP_EXTRA_ARGS": dl.get("yt_dlp_extra_args", None),
            "FFMPEG_EXTRA_ARGS": dl.get("ffmpeg_extra_args", None),
            "OUTPUT_EXTENSION": dl.get("output_extension", None),
            "FILENAME_TEMPLATE": dl.get("filename_template", None),
            "COLLISION_MODE": dl.get("collision_mode", None),
            "COOKIES_FILE": dl.get("cookies_file", None),
            "ALLOWED_DOMAINS": dl.get("allowed_domains", None),
            "LOUDNESS_NORMALIZE": dl.get("loudness_normalize", None),
            "LOUDNESS_TARGET_LUFS": dl.get("loudness_target_lufs", None),
            "LOUDNESS_AUDIO_BITRATE": dl.get("loudness_audio_bitrate", None),
            "SPONSORBLOCK_REMOVE": dl.get("sponsorblock_remove", None),
        }
    )

    # jobs section
    jobs = raw.get("jobs", {})
    flat.update(
        {
            "JOB_TIMEOUT_SECONDS": jobs.get("timeout_seconds", None),
            "RETRY_MAX": jobs.get("retry_max", None),
            "RETRY_INTERVAL_SECONDS": jobs.get("retry_intervals_seconds", None),
            "CLEANUP_TEMP_ON_SUCCESS": jobs.get("cleanup_temp_on_success", None),
            "CLEANUP_TEMP_ON_FAILURE": jobs.get("cleanup_temp_on_failure", None),
        }
    )

    # audiobookshelf section
    abs_cfg = raw.get("audiobookshelf", {})
    flat.update(
        {
            "ABS_BASE_URL": abs_cfg.get("base_url", None),
            "ABS_API_TOKEN": abs_cfg.get("api_token", None),
            "ABS_LIBRARY_ID": abs_cfg.get("library_id", None),
            "ABS_SCAN_AFTER_SUCCESS": abs_cfg.get("scan_after_success", None),
        }
    )

    # Remove None / blank values so Compose empties and missing YAML keys stay unset
    return {k: v for k, v in flat.items() if v is not None and v != ""}


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS_DEFAULT = [
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
]


def _get_default_data_dir() -> Path:
    """Return /data if writable/creatable, otherwise fallback to local ./data."""
    p = Path("/data")
    if check_writable_directory(p, create=True) is None:
        return p
    fallback = Path("./data")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Tell pydantic-settings to use comma as list delimiter for env vars
        env_nested_delimiter=None,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_host: str = Field("0.0.0.0", alias="APP_HOST")  # noqa: S104
    app_port: int = Field(8080, alias="APP_PORT")

    # ── Auth ─────────────────────────────────────────────────────────────────
    auth_enabled: bool = Field(False, alias="AUTH_ENABLED")
    auth_username: str | None = Field(None, alias="AUTH_USERNAME")
    auth_password: str | None = Field(None, alias="AUTH_PASSWORD")

    # ── Browser Extension API ──────────────────────────────────────────────
    extension_api_enabled: bool = Field(
        False,
        alias="EXTENSION_API_ENABLED",
        description="Enable extension API endpoints (returns 404 if false)",
    )
    extension_api_token: str | None = Field(
        None,
        alias="EXTENSION_API_TOKEN",
        description="Legacy shared bearer token. Prefer per-browser pairing.",
    )
    extension_public_url: str | None = Field(
        None,
        alias="EXTENSION_PUBLIC_URL",
        description="Advertised origin browsers should use to reach this instance.",
    )
    reeldock_config_mode: str = Field("ui", alias="REELDOCK_CONFIG_MODE")

    # ── Infrastructure ───────────────────────────────────────────────────────
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    database_url: str = Field(
        default_factory=lambda: f"sqlite+aiosqlite:///{_get_default_data_dir()}/app.db",
        alias="DATABASE_URL",
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    work_dir: Path = Field(
        default_factory=lambda: _get_default_data_dir() / "work", alias="WORK_DIR"
    )
    archive_file: Path = Field(
        default_factory=lambda: _get_default_data_dir() / "config" / "youtube-archive.txt",
        alias="ARCHIVE_FILE",
    )
    output_root: Path = Field(Path("/media/podcasts"), alias="OUTPUT_ROOT")
    cookies_file: Path | None = Field(None, alias="COOKIES_FILE")

    # ── Download ─────────────────────────────────────────────────────────────
    allow_playlists: bool = Field(False, alias="ALLOW_PLAYLISTS")
    allow_channels: bool = Field(False, alias="ALLOW_CHANNELS")
    max_playlist_entries: int = Field(100, alias="MAX_PLAYLIST_ENTRIES")
    default_destination_folder: str | None = Field(None, alias="DEFAULT_DESTINATION_FOLDER")

    ytdlp_bin: str = Field("yt-dlp", alias="YTDLP_BIN")
    ffmpeg_bin: str = Field("ffmpeg", alias="FFMPEG_BIN")
    ffprobe_bin: str = Field("ffprobe", alias="FFPROBE_BIN")
    ytdlp_audio_format: str = Field("m4a", alias="YTDLP_AUDIO_FORMAT")
    ytdlp_audio_quality: str = Field("", alias="YTDLP_AUDIO_QUALITY")
    ytdlp_extra_args: Any = Field(default_factory=lambda: [], alias="YTDLP_EXTRA_ARGS")
    ffmpeg_extra_args: Any = Field(default_factory=lambda: [], alias="FFMPEG_EXTRA_ARGS")

    output_extension: str = Field("m4b", alias="OUTPUT_EXTENSION")
    filename_template: str = Field("{title}.m4b", alias="FILENAME_TEMPLATE")
    collision_mode: str = Field("append_id", alias="COLLISION_MODE")

    loudness_normalize: bool = Field(False, alias="LOUDNESS_NORMALIZE")
    loudness_target_lufs: str = Field("-16", alias="LOUDNESS_TARGET_LUFS")
    loudness_audio_bitrate: str = Field("192k", alias="LOUDNESS_AUDIO_BITRATE")
    sponsorblock_remove: bool = Field(False, alias="SPONSORBLOCK_REMOVE")

    allowed_domains: Any = Field(
        default_factory=lambda: list(ALLOWED_DOMAINS_DEFAULT),
        alias="ALLOWED_DOMAINS",
    )

    # ── Jobs ─────────────────────────────────────────────────────────────────
    job_timeout_seconds: int = Field(10800, alias="JOB_TIMEOUT_SECONDS")
    retry_max: int = Field(3, alias="RETRY_MAX")
    retry_interval_seconds: Any = Field(
        default_factory=lambda: [60, 300, 900],
        alias="RETRY_INTERVAL_SECONDS",
    )
    cleanup_temp_on_success: bool = Field(True, alias="CLEANUP_TEMP_ON_SUCCESS")
    cleanup_temp_on_failure: bool = Field(False, alias="CLEANUP_TEMP_ON_FAILURE")

    # ── Audiobookshelf ────────────────────────────────────────────────────────
    abs_base_url: str | None = Field(None, alias="ABS_BASE_URL")
    abs_api_token: str | None = Field(None, alias="ABS_API_TOKEN")
    abs_library_id: str | None = Field(None, alias="ABS_LIBRARY_ID")
    abs_scan_after_success: bool = Field(False, alias="ABS_SCAN_AFTER_SUCCESS")

    # ── Dev ───────────────────────────────────────────────────────────────────
    dry_run: bool = Field(False, alias="DRY_RUN")
    # Test-only Compose release-smoke hook (#118). Never enable in production.
    release_smoke_fixture: bool = Field(False, alias="RELEASE_SMOKE_FIXTURE")
    release_smoke_fixture_dir: Path | None = Field(None, alias="RELEASE_SMOKE_FIXTURE_DIR")
    # When true with release_smoke_fixture, fail once after staging download (attempt 1).
    release_smoke_fail_once: bool = Field(False, alias="RELEASE_SMOKE_FAIL_ONCE")

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("ytdlp_extra_args", "ffmpeg_extra_args", mode="before")
    @classmethod
    def parse_space_separated_list(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, str):
            return [x for x in v.split() if x]
        return v

    @field_validator("retry_interval_seconds", mode="before")
    @classmethod
    def parse_int_list(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def parse_domains(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("collision_mode")
    @classmethod
    def validate_collision_mode(cls, v: str) -> str:
        from app.settings_registry import COLLISION_CHOICES

        if v not in COLLISION_CHOICES:
            raise ValueError(f"collision_mode must be one of {COLLISION_CHOICES}")
        return v

    @field_validator("extension_api_token", mode="before")
    @classmethod
    def validate_extension_api_token(cls, v: str) -> str | None:
        if v is None or v == "":
            return None
        # Optionally validate length if you want
        return v

    @field_validator("cookies_file", mode="before")
    @classmethod
    def parse_optional_path(cls, v: Any) -> Any:  # noqa: ANN401
        if v is None or v == "":
            return None
        return v

    @model_validator(mode="after")
    def validate_auth_credentials(self) -> Settings:
        """Refuse to start with Basic Auth enabled but empty credentials."""
        if self.auth_enabled:
            username = (self.auth_username or "").strip()
            password = (self.auth_password or "").strip()
            if not username or not password:
                raise ValueError(
                    "AUTH_ENABLED=true requires non-empty AUTH_USERNAME and AUTH_PASSWORD"
                )
        return self

    @field_validator("reeldock_config_mode", mode="before")
    @classmethod
    def validate_config_mode(cls, v: Any) -> str:  # noqa: ANN401
        raw = str(v or "ui").strip().lower()
        if raw not in {"ui", "locked"}:
            raise ValueError("REELDOCK_CONFIG_MODE must be 'ui' or 'locked'")
        return raw

    # ── Computed helpers ──────────────────────────────────────────────────────

    @property
    def abs_configured(self) -> bool:
        return bool(self.abs_base_url and self.abs_api_token and self.abs_library_id)

    @property
    def sync_database_url(self) -> str:
        """Synchronous database URL for use in RQ worker (not async)."""
        return self.database_url.replace("+aiosqlite", "")


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_settings: Settings | None = None
_pinned_sources: dict[str, str] = {}
_db_overrides: dict[str, str] = {}
_bootstrap_values: dict[str, Any] = {}

# Even in ui mode these stay deployment-locked when env/YAML provides a value.
DEPLOYMENT_BOUND_KEYS = frozenset({"output_root"})


def _parse_dotenv_keys() -> set[str]:
    """Return non-blank env var names declared in the project .env file."""
    return set(_parse_dotenv_values().keys())


def _parse_dotenv_values() -> dict[str, str]:
    env_path = Path(".env")
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        value = raw.strip().strip("'").strip('"')
        if value:
            values[key.strip()] = value
    return values


def _nonblank_env(alias: str) -> str | None:
    if alias in os.environ:
        raw = os.environ[alias]
        if raw != "":
            return raw
    if alias not in _parse_dotenv_keys():
        return None
    return _parse_dotenv_values().get(alias) or None


def _config_mode() -> str:
    raw = (_nonblank_env("REELDOCK_CONFIG_MODE") or "ui").strip().lower()
    return raw if raw in {"ui", "locked"} else "ui"


def _alias_to_field() -> dict[str, str]:
    return {
        (field.alias if isinstance(field.alias, str) else name): name
        for name, field in Settings.model_fields.items()
    }


def _yaml_as_field_map(yaml_flat: dict[str, Any]) -> dict[str, Any]:
    mapping = _alias_to_field()
    out: dict[str, Any] = {}
    for alias, value in yaml_flat.items():
        field_name = mapping.get(alias)
        if field_name is None:
            continue
        out[field_name] = value
    return out


def _env_as_field_map() -> dict[str, Any]:
    mapping = _alias_to_field()
    out: dict[str, Any] = {}
    for alias in mapping:
        raw = _nonblank_env(alias)
        if raw is None:
            continue
        out[mapping[alias]] = raw
    return out


def _collect_pinned_sources() -> dict[str, str]:
    """Return env aliases that lock the UI field."""
    from app.settings_registry import SETTINGS_REGISTRY

    mode = _config_mode()
    yaml_flat = _load_yaml()
    pinned: dict[str, str] = {}
    for spec in SETTINGS_REGISTRY:
        env_val = _nonblank_env(spec.env_alias)
        yaml_set = spec.env_alias in yaml_flat
        bound = spec.key in DEPLOYMENT_BOUND_KEYS or not spec.mutable
        locks = mode == "locked" or bound
        if env_val is not None and locks:
            pinned[spec.env_alias] = "env"
        elif yaml_set and locks:
            pinned[spec.env_alias] = "yaml"
    return pinned


def _load_db_override_map() -> dict[str, str]:
    """Return decrypted DB overrides keyed by Settings field name."""
    from app.models import AppSetting
    from app.secret_store import SecretStoreError, decrypt_secret, is_encrypted_value
    from app.settings_registry import SETTINGS_BY_KEY

    overrides: dict[str, str] = {}
    try:
        from sqlalchemy import select

        from app.db import get_sync_session_factory

        factory = get_sync_session_factory()
        with factory() as session:
            rows = session.scalars(select(AppSetting)).all()
            encrypted_present = any(is_encrypted_value(row.value) for row in rows)
            for row in rows:
                spec = SETTINGS_BY_KEY.get(row.key)
                if spec is None or not spec.mutable:
                    continue
                if row.value is None:
                    continue
                value = row.value
                if spec.secret or is_encrypted_value(value):
                    try:
                        value = decrypt_secret(value)
                    except SecretStoreError:
                        if encrypted_present:
                            raise
                        continue
                overrides[row.key] = value
    except SecretStoreError:
        raise
    except Exception:
        return overrides
    return overrides


def _settings_from_mapping(data: dict[str, Any]) -> Settings:
    """Validate a merged mapping without re-reading process environment."""

    class _Frozen(Settings):
        @classmethod
        def settings_customise_sources(  # type: ignore[override]
            cls,
            settings_cls: type,
            init_settings: object,
            env_settings: object,
            dotenv_settings: object,
            file_secret_settings: object,
        ) -> tuple[object, ...]:
            return (init_settings,)

    alias_data: dict[str, Any] = {}
    for name, field in Settings.model_fields.items():
        if name not in data:
            continue
        alias = field.alias if isinstance(field.alias, str) else name
        alias_data[alias] = data[name]
    return _Frozen(**alias_data)


def get_setting_sources() -> dict[str, dict[str, Any]]:
    """Return effective value, source, lock state, and display label."""
    from app.settings_registry import SETTINGS_REGISTRY, format_setting_value

    settings = get_settings()
    sources: dict[str, dict[str, Any]] = {}
    for spec in SETTINGS_REGISTRY:
        pinned_source = _pinned_sources.get(spec.env_alias)
        if spec.key in _db_overrides and not pinned_source:
            source = "db"
            label = "UI override"
            locked = False
        elif pinned_source:
            source = pinned_source
            label = (
                "Deployment locked"
                if (
                    not spec.mutable
                    or spec.key in DEPLOYMENT_BOUND_KEYS
                    or _config_mode() == "locked"
                )
                else "Deployment default"
            )
            locked = True
        elif spec.key in _bootstrap_values:
            source = "env"
            label = "Deployment default"
            locked = False
        else:
            source = "default"
            label = "Application default"
            locked = False
        if not spec.mutable:
            locked = True
            label = "Deployment locked"
        value = getattr(settings, spec.key)
        display = "" if spec.secret else format_setting_value(value, spec)
        sources[spec.key] = {
            "value": display,
            "source": source,
            "label": label,
            "locked": locked,
            "restart_required": spec.restart_required,
            "secret": spec.secret,
            "has_value": bool(value) if spec.secret else True,
        }
    return sources


def _merge_setting_layers(
    bootstrap: dict[str, Any],
    db_map: dict[str, Any],
    pinned: dict[str, str],
) -> dict[str, Any]:
    from app.settings_registry import SETTINGS_BY_KEY

    if _config_mode() == "locked":
        return {**db_map, **bootstrap}
    merged = {**bootstrap, **db_map}
    for spec in SETTINGS_BY_KEY.values():
        if spec.env_alias in pinned and spec.key in db_map and spec.key in bootstrap:
            merged[spec.key] = bootstrap[spec.key]
    return merged


def preview_merged_settings(
    overrides: dict[str, str],
    *,
    clear_keys: set[str] | None = None,
) -> Settings:
    """Build the Settings object that would result from a save, without writing."""
    from app.settings_registry import SETTINGS_BY_KEY

    get_settings()
    db_map = dict(_load_db_override_map())
    pinned = _collect_pinned_sources()
    for key in clear_keys or set():
        spec = SETTINGS_BY_KEY.get(key)
        if spec is None or not spec.mutable or spec.env_alias in pinned:
            continue
        db_map.pop(key, None)
    for key, value in overrides.items():
        spec = SETTINGS_BY_KEY.get(key)
        if spec is None or not spec.mutable or spec.env_alias in pinned:
            continue
        if spec.secret and value == "":
            continue
        db_map[key] = value
    merged = _merge_setting_layers(_bootstrap_values, db_map, pinned)
    try:
        return _settings_from_mapping(merged)
    except (ValidationError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def save_settings(overrides: dict[str, str], *, clear_keys: set[str] | None = None) -> None:
    """Persist UI overrides. Secrets are encrypted. Blank secrets are omitted."""
    from app.models import AppSetting
    from app.secret_store import encrypt_secret
    from app.settings_registry import SETTINGS_BY_KEY

    pinned = _collect_pinned_sources()
    to_clear = clear_keys or set()
    preview_merged_settings(overrides, clear_keys=to_clear)
    try:
        from app.db import get_sync_session_factory

        factory = get_sync_session_factory()
        with factory() as session:
            for key in to_clear:
                spec = SETTINGS_BY_KEY.get(key)
                if spec is None or not spec.mutable or spec.env_alias in pinned:
                    continue
                row = session.get(AppSetting, key)
                if row is not None:
                    session.delete(row)
            for key, value in overrides.items():
                spec = SETTINGS_BY_KEY.get(key)
                if spec is None or not spec.mutable:
                    continue
                if spec.env_alias in pinned:
                    continue
                if spec.secret and value == "":
                    continue
                stored = encrypt_secret(value) if spec.secret else value
                row = session.get(AppSetting, key)
                if row is None:
                    session.add(AppSetting(key=key, value=stored))
                else:
                    row.value = stored
            session.commit()
    except Exception as exc:
        raise RuntimeError(f"Failed to save settings: {exc}") from exc

    global _settings
    _settings = None


def reset_setting(key: str) -> None:
    """Remove a DB override so the deployment/default value is used again."""
    save_settings({}, clear_keys={key})


def reload_settings() -> Settings:
    """Force settings reload and return a fresh settings instance."""
    global _settings, _pinned_sources, _db_overrides, _bootstrap_values
    _settings = None
    _pinned_sources = {}
    _db_overrides = {}
    _bootstrap_values = {}
    return get_settings()


def get_settings() -> Settings:
    """Return cached Settings built from explicit sources (no os.environ mutation)."""
    global _settings, _pinned_sources, _db_overrides, _bootstrap_values
    if _settings is None:
        from app.settings_registry import SETTINGS_BY_KEY

        yaml_fields = _yaml_as_field_map(_load_yaml())
        env_fields = _env_as_field_map()
        bootstrap = {**yaml_fields, **env_fields}
        _bootstrap_values = dict(bootstrap)
        # Assign bootstrap first so get_sync_engine() re-entry during DB load
        # does not recurse into get_settings().
        _settings = _settings_from_mapping(bootstrap)
        db_map = _load_db_override_map()
        _pinned_sources = _collect_pinned_sources()
        merged = _merge_setting_layers(bootstrap, db_map, _pinned_sources)
        _db_overrides = {
            key: value
            for key, value in db_map.items()
            if SETTINGS_BY_KEY[key].env_alias not in _pinned_sources
        }
        _settings = _settings_from_mapping(merged)
    return _settings
