"""Test-only helpers for Compose release-smoke (#118).

Enabled only when ``RELEASE_SMOKE_FIXTURE=1``. Not a product feature.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Reserved allowlisted YouTube URL — never fetched when the fixture shim is on.
SMOKE_VIDEO_ID = "reeldockSmoke01"
SMOKE_URL = f"https://www.youtube.com/watch?v={SMOKE_VIDEO_ID}"
SMOKE_TITLE = "ReelDock Release Smoke"
SMOKE_UPLOADER = "ReelDock CI"
SMOKE_DURATION_SECONDS = 3

# Default path inside Compose when fixtures are bind-mounted.
DEFAULT_FIXTURE_DIR = Path("/fixtures/release_smoke")


def is_smoke_url(url: str) -> bool:
    return SMOKE_VIDEO_ID in (url or "")


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
