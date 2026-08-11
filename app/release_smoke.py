"""Test-only helpers for Compose release-smoke (#118).

Enabled only when ``RELEASE_SMOKE_FIXTURE=1``. Not a product feature.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Reserved allowlisted YouTube URLs — never fetched when the fixture shim is on.
SMOKE_VIDEO_ID = "reeldockSmoke01"
SMOKE_FAIL_VIDEO_ID = "reeldockSmokeFail01"
SMOKE_SLOW_VIDEO_ID = "reeldockSmokeSlow01"
# Longer ids first so prefix checks stay unambiguous.
SMOKE_VIDEO_IDS: tuple[str, ...] = (
    SMOKE_FAIL_VIDEO_ID,
    SMOKE_SLOW_VIDEO_ID,
    SMOKE_VIDEO_ID,
)
SMOKE_URL = f"https://www.youtube.com/watch?v={SMOKE_VIDEO_ID}"
SMOKE_TITLE = "ReelDock Release Smoke"
SMOKE_FAIL_TITLE = "ReelDock Smoke Fail"
SMOKE_SLOW_TITLE = "ReelDock Smoke Slow"
SMOKE_TITLES: dict[str, str] = {
    SMOKE_VIDEO_ID: SMOKE_TITLE,
    SMOKE_FAIL_VIDEO_ID: SMOKE_FAIL_TITLE,
    SMOKE_SLOW_VIDEO_ID: SMOKE_SLOW_TITLE,
}
SMOKE_UPLOADER = "ReelDock CI"
SMOKE_DURATION_SECONDS = 3

# Default path inside Compose when fixtures are bind-mounted.
DEFAULT_FIXTURE_DIR = Path("/fixtures/release_smoke")


def smoke_video_id_from_url(url: str) -> str | None:
    """Return the reserved fixture id contained in *url*, if any."""
    text = url or ""
    for video_id in SMOKE_VIDEO_IDS:
        if video_id in text:
            return video_id
    return None


def is_smoke_url(url: str) -> bool:
    return smoke_video_id_from_url(url) is not None


def smoke_title_for_id(video_id: str) -> str:
    return SMOKE_TITLES.get(video_id, SMOKE_TITLE)


def smoke_should_fail_first_attempt(video_id: str | None, url: str = "") -> bool:
    """True for the fail-once fixture id (retry should succeed)."""
    resolved = (video_id or "").strip() or smoke_video_id_from_url(url) or ""
    return resolved == SMOKE_FAIL_VIDEO_ID


def smoke_should_delay_after_stage(video_id: str | None, url: str = "") -> bool:
    """True for the slow fixture so Cancel can win the race."""
    resolved = (video_id or "").strip() or smoke_video_id_from_url(url) or ""
    return resolved == SMOKE_SLOW_VIDEO_ID


SMOKE_SLOW_POLL_SECONDS = 0.25
SMOKE_SLOW_POLLS = 40  # 10s cancel window


def resolve_fixture_dir(configured: Path | None) -> Path:
    """Return the directory that contains source.m4a (+ optional cover.jpg)."""
    if configured is not None:
        return configured
    repo_local = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "release_smoke"
    if (repo_local / "source.m4a").is_file():
        return repo_local
    return DEFAULT_FIXTURE_DIR


def stage_download_fixture(job_id: str, work_dir: Path, fixture_dir: Path) -> Path:
    """Copy canned audio into the job download dir; return the staged .m4a path."""
    source = fixture_dir / "source.m4a"
    if not source.is_file():
        raise FileNotFoundError(
            f"Release-smoke fixture missing: {source}. "
            "Mount tests/fixtures/release_smoke at RELEASE_SMOKE_FIXTURE_DIR."
        )
    download_dir = work_dir / job_id / "download"
    download_dir.mkdir(parents=True, exist_ok=True)
    dest = download_dir / f"{SMOKE_TITLE}.m4a"
    shutil.copy2(source, dest)

    cover = fixture_dir / "cover.jpg"
    if cover.is_file():
        shutil.copy2(cover, download_dir / "cover.jpg")
    return dest
