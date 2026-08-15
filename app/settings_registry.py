"""Metadata-driven configuration registry for the Settings UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.path_checks import check_writable_directory
from app.validators import (
    ValidationResult,
    validate_abs_url,
    validate_audio_bitrate,
    validate_extra_args,
    validate_filename_template,
    validate_lufs_target,
    validate_optional_path,
)


class SettingType(StrEnum):
    BOOL = "bool"
    INT = "int"
    STR = "str"
    PATH = "path"
    ENUM = "enum"
    CSV_LIST = "csv_list"
    SPACE_LIST = "space_list"
    INT_LIST = "int_list"


@dataclass(frozen=True)
class SettingSpec:
    """Declarative metadata for a single application setting."""

    key: str
    env_alias: str
    label: str
    group: str
    type: SettingType
    default: Any
    help_text: str = ""
    choices: tuple[str, ...] = ()
    mutable: bool = True
    secret: bool = False
    restart_required: bool = False
    validate: Callable[[str], ValidationResult] | None = None
    show_in_ui: bool = True


def _validate_absolute_writable_path(value: str) -> ValidationResult:
    error = check_writable_directory(Path(value.strip()), create=True)
    if error:
        return error, None
    return None, None


def _validate_positive_int(value: str) -> ValidationResult:
    try:
        parsed = int(value.strip())
    except ValueError:
        return "Must be a whole number.", None
    if parsed <= 0:
        return "Must be greater than zero.", None
    return None, None


def _validate_retry_max(value: str) -> ValidationResult:
    try:
        parsed = int(value.strip())
    except ValueError:
        return "Must be a whole number.", None
    if parsed < 0:
        return "Must be zero or greater.", None
    return None, None


def _validate_int_list(value: str) -> ValidationResult:
    stripped = value.strip()
    if not stripped:
        return "At least one interval is required.", None
    try:
        values = [int(x.strip()) for x in stripped.split(",") if x.strip()]
    except ValueError:
        return "Must be comma-separated integers.", None
    if not values:
        return "At least one interval is required.", None
    if any(v <= 0 for v in values):
        return "All intervals must be greater than zero.", None
    return None, None


COLLISION_CHOICES = ("skip", "overwrite", "append_id", "append_counter")

SETTINGS_REGISTRY: list[SettingSpec] = [
    # ── Paths ────────────────────────────────────────────────────────────────
    SettingSpec(
        key="output_root",
        env_alias="OUTPUT_ROOT",
        label="Audiobook Library Path",
        group="paths",
        type=SettingType.PATH,
        default="/media/podcasts",
        help_text=(
            "Folder where finished .m4b audiobooks are written (shared with Audiobookshelf). "
            "In the official Compose image this is the bind-mount target and stays read-only."
        ),
        validate=_validate_absolute_writable_path,
    ),
    SettingSpec(
        key="default_destination_folder",
        env_alias="DEFAULT_DESTINATION_FOLDER",
        label="Default Destination Folder",
        group="paths",
        type=SettingType.STR,
        default="",
        help_text="Optional subdirectory under the output root selected by default in the UI.",
    ),
    SettingSpec(
        key="cookies_file",
        env_alias="COOKIES_FILE",
        label="YouTube Cookies File",
        group="paths",
        type=SettingType.PATH,
        default="",
        help_text="Absolute path to a Netscape-format cookies file for yt-dlp.",
        validate=validate_optional_path,
    ),
    # ── Download behavior ────────────────────────────────────────────────────
    SettingSpec(
        key="collision_mode",
        env_alias="COLLISION_MODE",
        label="If Audiobook File Already Exists",
        group="processing",
        type=SettingType.ENUM,
        default="append_id",
        choices=COLLISION_CHOICES,
        help_text=(
            "skip keeps the file, overwrite replaces it, "
            "append_id / append_counter create a new filename."
        ),
    ),
    SettingSpec(
        key="output_extension",
        env_alias="OUTPUT_EXTENSION",
        label="Output Extension",
        group="processing",
        type=SettingType.STR,
        default="m4b",
        help_text="Legacy setting; final audiobooks are always written as .m4b.",
        show_in_ui=False,
    ),
    SettingSpec(
        key="allowed_domains",
        env_alias="ALLOWED_DOMAINS",
        label="Allowed Domains",
        group="expert",
        type=SettingType.CSV_LIST,
        default="youtube.com,www.youtube.com,m.youtube.com,music.youtube.com,youtu.be",
        help_text="Comma-separated hostnames permitted for import URLs.",
    ),
    SettingSpec(
        key="max_playlist_entries",
        env_alias="MAX_PLAYLIST_ENTRIES",
        label="Max Playlist / Channel Entries",
        group="processing",
        type=SettingType.INT,
        default="100",
        help_text=(
            "Maximum number of videos that can be enumerated or queued from a "
            "single playlist or channel submission."
        ),
        validate=_validate_positive_int,
    ),
    SettingSpec(
        key="ytdlp_extra_args",
        env_alias="YTDLP_EXTRA_ARGS",
        label="yt-dlp Extra Arguments",
        group="expert",
        type=SettingType.SPACE_LIST,
        default="",
        help_text="Space-separated extra arguments passed to yt-dlp.",
        validate=validate_extra_args,
    ),
    SettingSpec(
        key="ffmpeg_extra_args",
        env_alias="FFMPEG_EXTRA_ARGS",
        label="ffmpeg Extra Arguments",
        group="expert",
        type=SettingType.SPACE_LIST,
        default="",
        help_text="Space-separated extra arguments passed to ffmpeg.",
        validate=validate_extra_args,
    ),
    SettingSpec(
        key="loudness_normalize",
        env_alias="LOUDNESS_NORMALIZE",
        label="Normalize Loudness (EBU R128)",
        group="processing",
        type=SettingType.BOOL,
        default="false",
        help_text=(
            "Apply ffmpeg loudnorm during conversion. Re-encodes audio (AAC); "
            "stream copy is not used when enabled."
        ),
    ),
    SettingSpec(
        key="loudness_target_lufs",
        env_alias="LOUDNESS_TARGET_LUFS",
        label="Loudness Target (LUFS)",
        group="processing",
        type=SettingType.STR,
        default="-16",
        help_text="Integrated loudness target for loudnorm (typically -16 for podcasts).",
        validate=validate_lufs_target,
    ),
    SettingSpec(
        key="loudness_audio_bitrate",
        env_alias="LOUDNESS_AUDIO_BITRATE",
        label="Loudness Re-encode Bitrate",
        group="processing",
        type=SettingType.STR,
        default="192k",
        help_text="AAC bitrate used when loudness normalization re-encodes audio.",
        validate=validate_audio_bitrate,
    ),
    SettingSpec(
        key="sponsorblock_remove",
        env_alias="SPONSORBLOCK_REMOVE",
        label="Skip Sponsor Segments (SponsorBlock)",
        group="processing",
        type=SettingType.BOOL,
        default="false",
        help_text=("Remove sponsor segments from downloads using yt-dlp SponsorBlock integration."),
    ),
    # ── Naming ───────────────────────────────────────────────────────────────
    SettingSpec(
        key="filename_template",
        env_alias="FILENAME_TEMPLATE",
        label="Filename Template",
        group="processing",
        type=SettingType.STR,
        default="{title}.m4b",
        help_text=(
            "Template for the audiobook filename stem. Placeholders: {title}, "
            "{video_id}, {uploader}, {channel}, {upload_date}. ReelDock always "
            "appends .m4b (embedded media extensions in the template are stripped)."
        ),
        validate=validate_filename_template,
    ),
    # ── Jobs ─────────────────────────────────────────────────────────────────
    SettingSpec(
        key="job_timeout_seconds",
        env_alias="JOB_TIMEOUT_SECONDS",
        label="Job Timeout (seconds)",
        group="jobs",
        type=SettingType.INT,
        default="10800",
        help_text="Maximum runtime for a single import job.",
        validate=_validate_positive_int,
        restart_required=True,
    ),
    SettingSpec(
        key="retry_max",
        env_alias="RETRY_MAX",
        label="Retry Count",
        group="jobs",
        type=SettingType.INT,
        default="3",
        help_text="Maximum number of retry attempts after failure.",
        validate=_validate_retry_max,
    ),
    SettingSpec(
        key="retry_interval_seconds",
        env_alias="RETRY_INTERVAL_SECONDS",
        label="Retry Intervals (seconds)",
        group="jobs",
        type=SettingType.INT_LIST,
        default="60,300,900",
        help_text="Comma-separated wait times between retries.",
        validate=_validate_int_list,
    ),
    SettingSpec(
        key="cleanup_temp_on_success",
        env_alias="CLEANUP_TEMP_ON_SUCCESS",
        label="Cleanup Temp on Success",
        group="jobs",
        type=SettingType.BOOL,
        default="true",
        help_text="Remove temporary working files after a successful import.",
    ),
    SettingSpec(
        key="cleanup_temp_on_failure",
        env_alias="CLEANUP_TEMP_ON_FAILURE",
        label="Cleanup Temp on Failure",
        group="jobs",
        type=SettingType.BOOL,
        default="false",
        help_text="Remove temporary working files after a failed import.",
    ),
    # ── Runtime behavior ─────────────────────────────────────────────────────
    SettingSpec(
        key="dry_run",
        env_alias="DRY_RUN",
        label="Dry Run Mode",
        group="expert",
        type=SettingType.BOOL,
        default="false",
        help_text="Build commands and write a fake output file only.",
    ),
    SettingSpec(
        key="allow_playlists",
        env_alias="ALLOW_PLAYLISTS",
        label="Allow Playlist URLs",
        group="processing",
        type=SettingType.BOOL,
        default="false",
        help_text=(
            "Permit playlist URLs. When enabled, the import flow enumerates "
            "videos so you can select which ones to queue as a batch."
        ),
    ),
    SettingSpec(
        key="allow_channels",
        env_alias="ALLOW_CHANNELS",
        label="Allow Channel URLs",
        group="processing",
        type=SettingType.BOOL,
        default="false",
        help_text=(
            "Permit channel URLs. When enabled, the import flow enumerates "
            "videos so you can select which ones to queue as a batch."
        ),
    ),
    SettingSpec(
        key="abs_base_url",
        env_alias="ABS_BASE_URL",
        label="Audiobookshelf URL",
        group="abs",
        type=SettingType.STR,
        default="",
        help_text=(
            "Base URL of your Audiobookshelf server (for example http://abs:13378). "
            "Use Test Connection, then pick a library by name."
        ),
        validate=validate_abs_url,
    ),
    SettingSpec(
        key="abs_api_token",
        env_alias="ABS_API_TOKEN",
        label="Audiobookshelf API token",
        group="abs",
        type=SettingType.STR,
        default="",
        help_text="API token from Audiobookshelf. Leave blank to keep the current token.",
        secret=True,
    ),
    SettingSpec(
        key="abs_library_id",
        env_alias="ABS_LIBRARY_ID",
        label="Audiobookshelf library",
        group="abs",
        type=SettingType.STR,
        default="",
        help_text=(
            "Select a library after Test Connection. Audiobook (book) libraries are listed first. "
            "Save to persist the selection."
        ),
    ),
    SettingSpec(
        key="abs_scan_after_success",
        env_alias="ABS_SCAN_AFTER_SUCCESS",
        label="Default ABS scan after success",
        group="abs",
        type=SettingType.BOOL,
        default="false",
        help_text=(
            'Pre-checks the per-job "scan after success" checkbox. '
            "Each job's submitted value controls whether that job triggers a scan."
        ),
    ),
    SettingSpec(
        key="extension_api_enabled",
        env_alias="EXTENSION_API_ENABLED",
        label="Enable browser extension API",
        group="extension",
        type=SettingType.BOOL,
        default="false",
        help_text="Allow paired browsers (or a legacy shared token) to queue imports.",
    ),
    SettingSpec(
        key="extension_public_url",
        env_alias="EXTENSION_PUBLIC_URL",
        label="Advertised browser connection URL",
        group="extension",
        type=SettingType.STR,
        default="",
        help_text=(
            "Origin browsers should use to reach this instance "
            "(https://reeldock.example.com). Loopback is fine for local installs."
        ),
    ),
    SettingSpec(
        key="auth_enabled",
        env_alias="AUTH_ENABLED",
        label="Require Web UI sign-in",
        group="security",
        type=SettingType.BOOL,
        default="false",
        help_text="HTTP Basic Authentication for the Web UI. Enabling needs username and password.",
    ),
    SettingSpec(
        key="auth_username",
        env_alias="AUTH_USERNAME",
        label="Web UI username",
        group="security",
        type=SettingType.STR,
        default="",
    ),
    SettingSpec(
        key="auth_password",
        env_alias="AUTH_PASSWORD",
        label="Web UI password",
        group="security",
        type=SettingType.STR,
        default="",
        help_text="Leave blank to keep the current password. Never shown after save.",
        secret=True,
    ),
]

SECURITY_FORM_KEYS = frozenset({"auth_enabled", "auth_username", "auth_password"})
SECRET_KEEP_KEYS = frozenset({"auth_password", "abs_api_token"})

SETTINGS_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SETTINGS_REGISTRY}

GROUP_LABELS: dict[str, str] = {
    "paths": "Library",
    "processing": "Audiobook Processing",
    "abs": "Audiobookshelf",
    "extension": "Browser Extension",
    "security": "Security",
    "jobs": "Jobs",
    "expert": "Expert",
}

GROUP_ORDER: tuple[str, ...] = (
    "paths",
    "processing",
    "abs",
    "extension",
    "security",
    "jobs",
    "expert",
)


def registry_groups() -> list[tuple[str, str, list[SettingSpec]]]:
    """Return registry entries grouped for UI rendering."""
    grouped: dict[str, list[SettingSpec]] = {group: [] for group in GROUP_ORDER}
    for spec in SETTINGS_REGISTRY:
        if spec.show_in_ui:
            grouped.setdefault(spec.group, []).append(spec)
    return [
        (group, GROUP_LABELS.get(group, group.title()), grouped[group])
        for group in GROUP_ORDER
        if grouped.get(group)
    ]


def format_setting_value(value: object, spec: SettingSpec) -> str:
    """Serialize a Settings attribute to a string for forms/storage."""
    if value is None:
        return ""
    if spec.type is SettingType.BOOL:
        return "true" if bool(value) else "false"
    if spec.type in {SettingType.CSV_LIST, SettingType.INT_LIST}:
        if isinstance(value, list):
            if spec.type is SettingType.INT_LIST:
                return ",".join(str(v) for v in value)
            return ",".join(str(v) for v in value)
        return str(value)
    if spec.type is SettingType.SPACE_LIST:
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
        return str(value)
    if spec.type is SettingType.PATH:
        return str(value)
    return str(value)


def parse_form_value(raw: str | None, spec: SettingSpec) -> str:
    """Normalize a submitted form value to a storage string."""
    if spec.type is SettingType.BOOL:
        return "true" if raw in {"on", "true", "1", "yes"} else "false"
    return (raw or "").strip()


def coerce_storage_value(raw: str, spec: SettingSpec) -> object:
    """Convert a stored string to the Python type expected by Settings."""
    if spec.type is SettingType.BOOL:
        return raw.lower() in {"1", "true", "yes", "on"}
    if spec.type is SettingType.INT:
        return int(raw)
    if spec.type is SettingType.PATH:
        return Path(raw) if raw else None
    if spec.type is SettingType.ENUM:
        return raw
    if spec.type is SettingType.CSV_LIST:
        return [x.strip() for x in raw.split(",") if x.strip()]
    if spec.type is SettingType.SPACE_LIST:
        return [x for x in raw.split() if x]
    if spec.type is SettingType.INT_LIST:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    return raw
