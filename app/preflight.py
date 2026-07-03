"""Startup preflight checks for required writable paths."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.path_checks import check_writable_directory

_DOCS_PATH = "docs/paths-and-volumes.md"
_DEFAULT_RETRIES = 3
_DEFAULT_RETRY_DELAY_SECONDS = 2


@dataclass(frozen=True)
class PathCheckResult:
    name: str
    path: Path
    error: str | None  # None = ok


def check_required_paths(settings: Settings | None = None) -> list[PathCheckResult]:
    """Validate OUTPUT_ROOT and WORK_DIR; return one result per path."""
    cfg = settings or get_settings()
    results: list[PathCheckResult] = []

    output_error = check_writable_directory(cfg.output_root, create=False)
    results.append(PathCheckResult("OUTPUT_ROOT", cfg.output_root, output_error))

    work_error = check_writable_directory(cfg.work_dir, create=True)
    results.append(PathCheckResult("WORK_DIR", cfg.work_dir, work_error))

    return results


def _preflight_retries() -> int:
    raw = os.getenv("PREFLIGHT_RETRIES", str(_DEFAULT_RETRIES)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_RETRIES


def _preflight_retry_delay_seconds() -> float:
    raw = os.getenv("PREFLIGHT_RETRY_DELAY", str(_DEFAULT_RETRY_DELAY_SECONDS)).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(_DEFAULT_RETRY_DELAY_SECONDS)


def _format_error(name: str, path: Path, error: str) -> str:
    puid = os.getenv("PUID", "1000")
    pgid = os.getenv("PGID", "1000")
    return "\n".join(
        [
            f"ERROR: {name} '{path}' is not writable: {error}",
            "- Confirm HOST_PODCASTS_DIR in .env points to an existing host directory"
            if name == "OUTPUT_ROOT"
            else f"- Confirm {name} is mounted and accessible inside the container",
            "- On macOS, mount the share and add /Volumes to Docker Desktop File Sharing",
            f"- Set PUID/PGID ({puid}:{pgid}) to match the directory owner (see {_DOCS_PATH})",
        ]
    )


def run_preflight() -> int:
    """Validate critical paths before starting app or worker."""
    retries = _preflight_retries()
    delay_seconds = _preflight_retry_delay_seconds()
    failures: list[PathCheckResult] = []

    for attempt in range(1, retries + 1):
        print(f"Preflight attempt {attempt}/{retries}...")
        failures = [r for r in check_required_paths() if r.error is not None]
        if not failures:
            return 0
        if attempt < retries and delay_seconds > 0:
            time.sleep(delay_seconds)

    for result in failures:
        assert result.error is not None
        print(_format_error(result.name, result.path, result.error), file=sys.stderr)
        print(file=sys.stderr)

    return 1


def main() -> None:
    raise SystemExit(run_preflight())


if __name__ == "__main__":
    main()
