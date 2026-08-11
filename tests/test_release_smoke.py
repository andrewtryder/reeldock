"""Unit coverage for the release-smoke fixture shim."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.release_smoke import (
    SMOKE_FAIL_TITLE,
    SMOKE_FAIL_VIDEO_ID,
    SMOKE_SLOW_TITLE,
    SMOKE_SLOW_VIDEO_ID,
    SMOKE_TITLE,
    SMOKE_URL,
    SMOKE_VIDEO_ID,
    is_smoke_url,
    resolve_fixture_dir,
    smoke_should_delay_after_stage,
    smoke_should_fail_first_attempt,
    smoke_video_id_from_url,
    stage_download_fixture,
)
from app.services.ytdlp import YtDlpService


def test_is_smoke_url() -> None:
    assert is_smoke_url(SMOKE_URL)
    assert is_smoke_url(f"https://youtu.be/{SMOKE_VIDEO_ID}")
    assert is_smoke_url(f"https://www.youtube.com/watch?v={SMOKE_FAIL_VIDEO_ID}")
    assert is_smoke_url(f"https://www.youtube.com/watch?v={SMOKE_SLOW_VIDEO_ID}")
    assert smoke_video_id_from_url(f"https://youtu.be/{SMOKE_FAIL_VIDEO_ID}") == SMOKE_FAIL_VIDEO_ID
    assert smoke_video_id_from_url(f"https://youtu.be/{SMOKE_SLOW_VIDEO_ID}") == SMOKE_SLOW_VIDEO_ID
    assert not is_smoke_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")


def test_stage_download_fixture(tmp_path: Path) -> None:
    fixture_dir = resolve_fixture_dir(None)
    assert (fixture_dir / "source.m4a").is_file()
    staged = stage_download_fixture("job-smoke", tmp_path, fixture_dir)
    assert staged.is_file()
    assert staged.suffix == ".m4a"
    assert SMOKE_TITLE in staged.name
    assert staged.stat().st_size > 0


def test_run_preview_smoke_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_SMOKE_FIXTURE", "true")
    # Rebuild settings after env change
    import app.config as cfg_module

    cfg_module._settings = None
    from app.config import Settings

    settings = Settings()
    settings.release_smoke_fixture = True
    meta = YtDlpService(settings).run_preview(SMOKE_URL)
    assert meta.id == SMOKE_VIDEO_ID
    assert meta.title == SMOKE_TITLE
    fail_meta = YtDlpService(settings).run_preview(
        f"https://www.youtube.com/watch?v={SMOKE_FAIL_VIDEO_ID}"
    )
    assert fail_meta.id == SMOKE_FAIL_VIDEO_ID
    assert fail_meta.title == SMOKE_FAIL_TITLE
    slow_meta = YtDlpService(settings).run_preview(
        f"https://www.youtube.com/watch?v={SMOKE_SLOW_VIDEO_ID}"
    )
    assert slow_meta.id == SMOKE_SLOW_VIDEO_ID
    assert slow_meta.title == SMOKE_SLOW_TITLE
    assert smoke_should_fail_first_attempt(SMOKE_FAIL_VIDEO_ID)
    assert not smoke_should_fail_first_attempt(SMOKE_VIDEO_ID)
    assert smoke_should_delay_after_stage(SMOKE_SLOW_VIDEO_ID)
    assert not smoke_should_delay_after_stage(SMOKE_VIDEO_ID)


def test_stage_download_fixture_missing_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="fixture missing"):
        stage_download_fixture("job-x", tmp_path / "work", empty)
