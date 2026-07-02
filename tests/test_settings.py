from __future__ import annotations

import json
from pathlib import Path

import app.config as config_module
import pytest
from app.config import get_settings, save_custom_settings
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def mock_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(config_module, "_get_default_data_dir", lambda: data_dir)
    return data_dir


def test_save_and_load_custom_settings(mock_data_dir: Path):
    # Verify default path
    s1 = get_settings()
    assert s1.output_root == Path("/media/podcasts")

    # Save custom output root
    custom_path = mock_data_dir / "my_custom_podcasts"
    custom_path.mkdir()
    save_custom_settings(
        str(custom_path),
        dry_run=True,
        allow_playlists=True,
        allow_channels=True,
        abs_scan_after_success=True,
    )

    # Verify settings are reloaded correctly
    s2 = get_settings()
    assert s2.output_root == custom_path
    assert s2.dry_run is True
    assert s2.allow_playlists is True
    assert s2.allow_channels is True
    assert s2.abs_scan_after_success is True

    # Verify settings.json file contents
    settings_file = mock_data_dir / "settings.json"
    assert settings_file.exists()
    with settings_file.open() as fh:
        data = json.load(fh)
    assert data["output_root"] == str(custom_path)
    assert data["dry_run"] is True
    assert data["allow_playlists"] is True
    assert data["allow_channels"] is True
    assert data["abs_scan_after_success"] is True


def test_get_settings_page(mock_data_dir: Path):
    client = TestClient(app)
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Settings" in response.text
    assert "Output Root Directory" in response.text
    assert "/media/podcasts" in response.text


def test_post_settings_valid(mock_data_dir: Path, tmp_path: Path):
    client = TestClient(app)
    valid_path = tmp_path / "new_output"
    # POST to /settings with a valid writable path
    response = client.post(
        "/settings",
        data={
            "output_root": str(valid_path),
            "dry_run": "on",
            "allow_playlists": "on",
            "allow_channels": "on",
            "abs_scan_after_success": "on",
        },
    )
    assert response.status_code == 200
    assert "Settings saved successfully" in response.text
    assert str(valid_path) in response.text

    # Verify it was updated in config
    settings = get_settings()
    assert settings.output_root == valid_path
    assert settings.dry_run is True
    assert settings.allow_playlists is True
    assert settings.allow_channels is True
    assert settings.abs_scan_after_success is True


def test_post_settings_relative(mock_data_dir: Path):
    client = TestClient(app)
    # Relative path is invalid
    response = client.post("/settings", data={"output_root": "some/relative/path"})
    assert response.status_code == 400
    assert "must be an absolute path" in response.text


def test_post_settings_non_writable(mock_data_dir: Path):
    client = TestClient(app)
    # A path that exists but is not writable (e.g. a file instead of a directory)
    fake_file = mock_data_dir / "not_a_dir"
    fake_file.touch()
    response = client.post("/settings", data={"output_root": str(fake_file)})
    assert response.status_code == 400
    assert "not writable" in response.text
