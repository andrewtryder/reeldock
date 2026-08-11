"""Tests for shared quality preset mapping."""

from __future__ import annotations

import pytest
from app.quality import QUALITY_PRESETS, audio_quality_for_preset


def test_quality_presets_match_web_ui() -> None:
    assert QUALITY_PRESETS == {"standard": "128K", "high": "192K", "best": "0"}


def test_audio_quality_for_preset() -> None:
    assert audio_quality_for_preset("standard") == "128K"
    assert audio_quality_for_preset("HIGH") == "192K"
    assert audio_quality_for_preset("best") == "0"


def test_audio_quality_for_preset_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown quality"):
        audio_quality_for_preset("ultra")
