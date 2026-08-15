"""Persistent ReelDock instance identity for extension pairing probes."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from app.secret_store import DEFAULT_KEY_PATH

logger = logging.getLogger(__name__)

DEFAULT_INSTANCE_ID_PATH = DEFAULT_KEY_PATH.with_name(".reeldock-instance-id")

_MEM_INSTANCE_ID: dict[Path, str] = {}


def instance_id_path() -> Path:
    override = os.getenv("REELDOCK_INSTANCE_ID_FILE", "").strip()
    if override:
        return Path(override)
    return DEFAULT_INSTANCE_ID_PATH


def get_or_create_instance_id(path: Path | None = None) -> str:
    """Return a stable UUID for this ReelDock install (generate-once)."""
    target = path or instance_id_path()
    try:
        if target.exists():
            raw = target.read_text(encoding="utf-8").strip()
            if raw:
                _MEM_INSTANCE_ID[target] = raw
                return raw
    except OSError:
        logger.warning("Could not read instance id at %s", target, exc_info=True)

    if target in _MEM_INSTANCE_ID:
        return _MEM_INSTANCE_ID[target]

    value = str(uuid.uuid4())
    _MEM_INSTANCE_ID[target] = value
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value + "\n", encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            logger.warning("Could not set 0600 permissions on instance id file")
    except OSError:
        logger.warning(
            "Could not persist instance id at %s; using ephemeral id", target, exc_info=True
        )
    return value
