"""Shared validation helpers for settings and per-job import options."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

ValidationResult = tuple[str | None, str | None]  # (error, warning)

_SHELL_INJECTION_RE = re.compile(r"[;|&`><]|&&|\|\||\$\(")


def validate_optional_path(value: str) -> ValidationResult:
    stripped = value.strip()
    if not stripped:
        return None, None
    p = Path(stripped)
    if not p.is_absolute():
        return "Path must be absolute.", None
    if not p.exists():
        return None, "File does not exist yet; yt-dlp will fail until it is created."
    if not p.is_file():
        return "Path must point to a file.", None
    if not os.access(p, os.R_OK):
        return "File is not readable.", None
    return None, None


def validate_extra_args(value: str) -> ValidationResult:
    stripped = value.strip()
    if not stripped:
        return None, None
    if _SHELL_INJECTION_RE.search(stripped):
        return "Arguments must not contain shell metacharacters (; | & ` > < && || $( ).", None
    warnings: list[str] = []
    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        return f"Could not parse arguments: {exc}", None
    for token in tokens:
        if not token.startswith("-"):
            warnings.append(f'Unusual token "{token}" does not look like a flag.')
    warning = " ".join(warnings) if warnings else None
    return None, warning


def validate_filename_template(value: str) -> ValidationResult:
    stripped = value.strip()
    if not stripped:
        return "Filename template cannot be empty.", None
    if ".." in stripped or "/" in stripped or "\\" in stripped:
        return "Template must not contain path separators.", None
    return None, None
