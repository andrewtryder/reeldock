"""Shared filesystem path validation helpers."""

from __future__ import annotations

import errno
from pathlib import Path


def _format_os_error(path: Path, exc: OSError, *, create: bool) -> str:
    if exc.errno == errno.ENOENT:
        if not create:
            return f"Path does not exist or the bind mount is not available yet: {path}"
        return (
            f"Path is not writable: bind mount may not be ready yet ({path}). "
            f"Original error: {exc}"
        )
    return f"Path is not writable: {exc}"


def check_writable_directory(path: Path, *, create: bool = True) -> str | None:
    """Return an error message if *path* is not an absolute writable directory."""
    if not path.is_absolute():
        return "Path must be absolute."

    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            return f"Path does not exist or the bind mount is not available yet: {path}"

        test_file = path / ".write_test"
        test_file.touch()
        test_file.unlink()
    except OSError as exc:
        return _format_os_error(path, exc, create=create)

    return None
