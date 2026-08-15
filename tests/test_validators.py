"""Tests for shared validation helpers."""

from __future__ import annotations

from app.validators import validate_audio_bitrate, validate_lufs_target


def test_validate_lufs_target_accepts_negative_values():
    assert validate_lufs_target("-16") == (None, None)
    assert validate_lufs_target("-23.0") == (None, None)


def test_validate_lufs_target_rejects_positive_values():
    error, _warning = validate_lufs_target("3")
    assert error is not None
    assert "negative" in error.lower()


def test_validate_lufs_target_rejects_out_of_range():
    error, _warning = validate_lufs_target("-80")
    assert error is not None


def test_validate_audio_bitrate_accepts_k_suffix():
    assert validate_audio_bitrate("192k") == (None, None)
    assert validate_audio_bitrate("128K") == (None, None)


def test_validate_audio_bitrate_accepts_plain_integer():
    assert validate_audio_bitrate("192000") == (None, None)


def test_validate_audio_bitrate_rejects_invalid():
    error, _warning = validate_audio_bitrate("fast")
    assert error is not None


def test_validate_abs_url_accepts_valid_urls():
    from app.validators import validate_abs_url

    assert validate_abs_url("") == (None, None)
    assert validate_abs_url("   ") == (None, None)
    assert validate_abs_url("http://audiobookshelf:13378") == (None, None)
    assert validate_abs_url("http://192.168.1.20:13378") == (None, None)
    assert validate_abs_url("https://abs.example.com") == (None, None)
    assert validate_abs_url("http://localhost:13378/abs") == (None, None)


def test_validate_abs_url_rejects_invalid_urls():
    from app.validators import validate_abs_url

    assert validate_abs_url("javascript:alert(1)")[0] is not None
    assert validate_abs_url("file:///etc/passwd")[0] is not None
    assert validate_abs_url("ftp://server/path")[0] is not None
    assert validate_abs_url("http://user:password@abs.local:13378")[0] is not None
    assert validate_abs_url("http://abs.local:13378?query=1")[0] is not None
    assert validate_abs_url("http://abs.local:13378#fragment")[0] is not None
    assert validate_abs_url("just-a-string")[0] is not None
