"""Tests for instance ID generation and fail-stable caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.instance_id import _MEM_INSTANCE_ID, get_or_create_instance_id


def test_instance_id_reads_existing_file(tmp_path: Path):
    target = tmp_path / "sub" / "instance-id.txt"
    target.parent.mkdir(parents=True)
    target.write_text("inst-fixed-uuid\n", encoding="utf-8")

    _MEM_INSTANCE_ID.clear()
    val = get_or_create_instance_id(target)
    assert val == "inst-fixed-uuid"


def test_instance_id_generates_and_persists_to_file(tmp_path: Path):
    target = tmp_path / "sub" / "new-instance-id.txt"

    _MEM_INSTANCE_ID.clear()
    val = get_or_create_instance_id(target)
    assert len(val) >= 32
    assert target.is_file()
    assert target.read_text(encoding="utf-8").strip() == val


def test_instance_id_fail_stable_when_unwritable(tmp_path: Path):
    target = tmp_path / "non-writable" / "id.txt"

    _MEM_INSTANCE_ID.clear()
    with patch("pathlib.Path.write_text", side_effect=OSError("Read-only file system")):
        val1 = get_or_create_instance_id(target)
        val2 = get_or_create_instance_id(target)

    assert val1 == val2
    assert len(val1) >= 32
