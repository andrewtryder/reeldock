"""Shared audio quality presets for the Web UI and extension API.

Maps user-facing preset names to yt-dlp ``--audio-quality`` values.
The final audiobook container is always ``.m4b``.
"""

from __future__ import annotations

QUALITY_PRESETS: dict[str, str] = {
    "standard": "128K",
    "high": "192K",
    "best": "0",
}

QUALITY_PRESET_NAMES = frozenset(QUALITY_PRESETS)


def audio_quality_for_preset(quality: str) -> str:
    """Return the yt-dlp audio-quality value for a named preset.

    Raises ``ValueError`` when *quality* is not a known preset.
    """
    key = (quality or "standard").strip().lower()
    try:
        return QUALITY_PRESETS[key]
    except KeyError:
        raise ValueError(
            f"Unknown quality '{quality}'. Expected standard, high, or best."
        ) from None
