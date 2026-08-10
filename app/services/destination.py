"""Shared audiobook destination resolution for Preview and job submit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config import Settings
from app.services.filesystem import FilesystemService, resolve_safe_path


def resolve_destination_folder(
    *,
    new_folder: str = "",
    destination_folder: str = "",
    default_destination_folder: str | None = None,
) -> str:
    """Resolve the relative destination folder using submit precedence.

    Precedence (preview-safe; does not create directories):
      1. non-empty ``new_folder``
      2. non-empty ``destination_folder``
      3. configured ``default_destination_folder``
      4. empty string → audiobook library root (OUTPUT_ROOT)
    """
    new_stripped = (new_folder or "").strip()
    if new_stripped:
        return new_stripped

    selected = (destination_folder or "").strip()
    if selected:
        return selected

    default = (default_destination_folder or "").strip()
    if default:
        return default

    return ""


def blank_destination_option_label(default_destination_folder: str | None) -> str:
    """User-facing label for the blank Destination Folder select option."""
    default = (default_destination_folder or "").strip()
    if default:
        return f"— Use default: {default} —"
    return "— Use library root —"


def format_folder_display_path(output_root: Path, destination_folder: str) -> str:
    """Absolute folder path for display, always with a trailing slash."""
    folder = resolve_safe_path(output_root, destination_folder)
    text = str(folder)
    return text if text.endswith("/") else f"{text}/"


@dataclass(frozen=True)
class DestinationPreview:
    """Product-facing destination summary for Preview screens."""

    destination_folder: str
    folder_path: str
    filename: str | None
    blank_option_label: str
    summary_kind: Literal["single", "batch"]
    heading: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "destination_folder": self.destination_folder,
            "folder_path": self.folder_path,
            "filename": self.filename,
            "blank_option_label": self.blank_option_label,
            "summary_kind": self.summary_kind,
            "heading": self.heading,
        }


def preview_audiobook_destination(
    settings: Settings,
    *,
    new_folder: str = "",
    destination_folder: str = "",
    output_title: str = "",
    video_id: str = "",
    filename_template: str | None = None,
    collision_mode: str | None = None,
    uploader: str | None = None,
    channel: str | None = None,
    upload_date: str | None = None,
    summary_kind: Literal["single", "batch"] = "single",
) -> DestinationPreview:
    """Resolve the display destination using the same rules as job creation."""
    resolved = resolve_destination_folder(
        new_folder=new_folder,
        destination_folder=destination_folder,
        default_destination_folder=settings.default_destination_folder,
    )
    folder_path = format_folder_display_path(settings.output_root, resolved)
    blank_label = blank_destination_option_label(settings.default_destination_folder)

    filename: str | None = None
    heading = "Audiobooks will be saved to"
    if summary_kind == "single":
        heading = "Audiobook destination"
        title = (output_title or "").strip() or "untitled"
        fs = FilesystemService(settings)
        final_path = fs.resolve_output_path(
            resolved,
            title,
            (video_id or "").strip() or "unknown",
            collision_mode=collision_mode or None,
            filename_template=(filename_template or "").strip() or None,
            uploader=uploader,
            channel=channel,
            upload_date=upload_date,
        )
        filename = final_path.name

    return DestinationPreview(
        destination_folder=resolved,
        folder_path=folder_path,
        filename=filename,
        blank_option_label=blank_label,
        summary_kind=summary_kind,
        heading=heading,
    )


def initial_selected_destination_folder(
    folders: list[str],
    *,
    default_folder: str = "",
    uploader: str | None = None,
    uploader_id: str | None = None,
    channel: str | None = None,
    match_channel: bool = False,
) -> str:
    """Mirror Preview Jinja preselect: last matching folder wins (browser behavior)."""
    selected = ""
    for folder in folders:
        if (
            folder == default_folder
            or (uploader_id and folder == uploader_id)
            or (uploader and folder == uploader)
            or (match_channel and channel and folder == channel)
        ):
            selected = folder
    return selected
