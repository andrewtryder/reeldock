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
    destination_folder: str | None = None,
    default_destination_folder: str | None = None,
) -> str:
    """Resolve the relative destination folder using submit precedence.

    Precedence (preview-safe; does not create directories):
      1. non-empty ``new_folder``
      2. ``destination_folder is None`` → configured default (or library root)
      3. ``destination_folder == ""`` → explicit library root (OUTPUT_ROOT)
      4. non-empty ``destination_folder`` → that folder
    """
    new_stripped = (new_folder or "").strip()
    if new_stripped:
        return new_stripped

    if destination_folder is None:
        return (default_destination_folder or "").strip()

    return destination_folder.strip()


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
    destination_folder: str | None = None,
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
    """Pick exactly one preselect with explicit precedence.

    Order: configured default → uploader ID → uploader name → channel (optional).
    Returns ``\"\"`` when nothing matches (library root / blank option).
    """
    folder_set = set(folders)
    if default_folder and default_folder in folder_set:
        return default_folder
    if uploader_id and uploader_id in folder_set:
        return uploader_id
    if uploader and uploader in folder_set:
        return uploader
    if match_channel and channel and channel in folder_set:
        return channel
    return ""
