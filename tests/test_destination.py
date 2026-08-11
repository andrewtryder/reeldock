"""Tests for shared audiobook destination resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings
from app.services.destination import (
    blank_destination_option_label,
    initial_selected_destination_folder,
    preview_audiobook_destination,
    resolve_destination_folder,
)


def test_resolve_selected_folder_when_new_empty():
    assert (
        resolve_destination_folder(
            new_folder="",
            destination_folder="Podcasts",
            default_destination_folder="Default",
        )
        == "Podcasts"
    )


def test_resolve_new_folder_overrides_selected():
    assert (
        resolve_destination_folder(
            new_folder="Brand New",
            destination_folder="Podcasts",
            default_destination_folder="Default",
        )
        == "Brand New"
    )


def test_resolve_configured_default_when_omitted():
    assert (
        resolve_destination_folder(
            new_folder="  ",
            destination_folder=None,
            default_destination_folder="Podcasts",
        )
        == "Podcasts"
    )


def test_resolve_explicit_root_ignores_configured_default():
    assert (
        resolve_destination_folder(
            new_folder="",
            destination_folder="",
            default_destination_folder="Podcasts",
        )
        == ""
    )


def test_resolve_library_root_when_no_default():
    assert (
        resolve_destination_folder(
            new_folder="",
            destination_folder=None,
            default_destination_folder=None,
        )
        == ""
    )


def test_blank_option_labels():
    assert blank_destination_option_label(None) == "— Use library root —"
    assert blank_destination_option_label("") == "— Use library root —"
    assert blank_destination_option_label("Podcasts") == "— Use default: Podcasts —"


def test_preview_single_filename_and_extension(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = None
    settings.filename_template = "{title}.m4b"
    settings.collision_mode = "overwrite"

    preview = preview_audiobook_destination(
        settings,
        destination_folder="Shows",
        output_title="How To Fix A GE Front Load Washer",
        video_id="abc123",
        summary_kind="single",
    )
    assert preview.destination_folder == "Shows"
    assert preview.folder_path == str(output_root / "Shows") + "/"
    assert preview.filename == "How To Fix A GE Front Load Washer.m4b"
    assert preview.filename.endswith(".m4b")
    assert preview.summary_kind == "single"
    assert "destination" in preview.heading.lower()


def test_preview_output_title_change_updates_filename(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = None
    settings.filename_template = "{title}"
    settings.collision_mode = "overwrite"

    a = preview_audiobook_destination(
        settings, output_title="Title A", video_id="v1", summary_kind="single"
    )
    b = preview_audiobook_destination(
        settings, output_title="Title B", video_id="v1", summary_kind="single"
    )
    assert a.filename == "Title A.m4b"
    assert b.filename == "Title B.m4b"


def test_preview_strips_template_extension_to_m4b(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = None
    settings.filename_template = "{title}.mp3"
    settings.collision_mode = "overwrite"

    preview = preview_audiobook_destination(
        settings,
        output_title="Episode One",
        video_id="vid",
        filename_template="{title}.mp3",
        summary_kind="single",
    )
    assert preview.filename == "Episode One.m4b"


def test_preview_default_folder_and_library_root(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = "Podcasts"
    settings.collision_mode = "overwrite"

    with_default = preview_audiobook_destination(
        settings, output_title="T", video_id="v", summary_kind="single"
    )
    assert with_default.destination_folder == "Podcasts"
    assert with_default.folder_path.endswith("Podcasts/")

    settings.default_destination_folder = None
    at_root = preview_audiobook_destination(
        settings, output_title="T", video_id="v", summary_kind="single"
    )
    assert at_root.destination_folder == ""
    assert at_root.folder_path == str(output_root.resolve()) + "/"


def test_preview_path_stays_under_output_root(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = None

    with pytest.raises(ValueError, match="Path traversal"):
        preview_audiobook_destination(
            settings,
            new_folder="../outside",
            output_title="T",
            video_id="v",
            summary_kind="single",
        )


def test_preview_batch_folder_only(tmp_path: Path):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    settings = Settings()
    settings.output_root = output_root
    settings.default_destination_folder = None

    preview = preview_audiobook_destination(
        settings,
        destination_folder="BatchShow",
        summary_kind="batch",
    )
    assert preview.filename is None
    assert preview.destination_folder == "BatchShow"
    assert preview.folder_path.endswith("BatchShow/")
    assert "audiobooks" in preview.heading.lower()


def test_initial_selected_destination_folder_prefers_default():
    folders = ["Podcasts", "DuctTapeMechanic", "Other"]
    selected = initial_selected_destination_folder(
        folders,
        default_folder="Podcasts",
        uploader="DuctTapeMechanic",
        uploader_id=None,
    )
    assert selected == "Podcasts"


def test_initial_selected_destination_folder_uploader_id_before_name():
    folders = ["ChannelName", "UC123", "Other"]
    selected = initial_selected_destination_folder(
        folders,
        default_folder="",
        uploader="ChannelName",
        uploader_id="UC123",
    )
    assert selected == "UC123"
