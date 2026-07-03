"""Tests for app.preflight startup checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from app import preflight


@pytest.fixture(autouse=True)
def fast_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREFLIGHT_RETRIES", "1")
    monkeypatch.setenv("PREFLIGHT_RETRY_DELAY", "0")


def test_run_preflight_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    settings = SimpleNamespace(
        output_root=tmp_path / "podcasts",
        work_dir=tmp_path / "work",
    )
    settings.output_root.mkdir()
    settings.work_dir.mkdir()

    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    assert preflight.run_preflight() == 0


def test_run_preflight_fails_on_unwritable_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    settings = SimpleNamespace(
        output_root=tmp_path / "missing-podcasts",
        work_dir=work_dir,
    )

    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    assert preflight.run_preflight() == 1
    captured = capsys.readouterr()
    assert "OUTPUT_ROOT" in captured.err
    assert "HOST_PODCASTS_DIR" in captured.err


def test_run_preflight_fails_on_unwritable_work_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    output_root = tmp_path / "podcasts"
    output_root.mkdir()
    work_file = tmp_path / "not-a-directory"
    work_file.write_text("x")
    settings = SimpleNamespace(output_root=output_root, work_dir=work_file)

    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    assert preflight.run_preflight() == 1
    captured = capsys.readouterr()
    assert "WORK_DIR" in captured.err


def test_run_preflight_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    settings = SimpleNamespace(
        output_root=tmp_path / "podcasts",
        work_dir=tmp_path / "work",
    )
    settings.output_root.mkdir()
    settings.work_dir.mkdir()
    attempts = {"count": 0}
    original_check = preflight.check_required_paths

    def flaky_check(settings_arg=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return [preflight.PathCheckResult("OUTPUT_ROOT", settings.output_root, "not ready")]
        return original_check(settings)

    monkeypatch.setenv("PREFLIGHT_RETRIES", "3")
    monkeypatch.setenv("PREFLIGHT_RETRY_DELAY", "0")
    monkeypatch.setattr(preflight, "check_required_paths", flaky_check)

    assert preflight.run_preflight() == 0
    captured = capsys.readouterr()
    assert "Preflight attempt 1/3" in captured.out
    assert "Preflight attempt 2/3" in captured.out


def test_run_preflight_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    settings = SimpleNamespace(
        output_root=tmp_path / "missing-podcasts",
        work_dir=tmp_path / "work",
    )
    settings.work_dir.mkdir()

    monkeypatch.setenv("PREFLIGHT_RETRIES", "3")
    monkeypatch.setenv("PREFLIGHT_RETRY_DELAY", "0")
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    assert preflight.run_preflight() == 1
    captured = capsys.readouterr()
    assert "Preflight attempt 1/3" in captured.out
    assert "Preflight attempt 3/3" in captured.out
    assert "OUTPUT_ROOT" in captured.err
