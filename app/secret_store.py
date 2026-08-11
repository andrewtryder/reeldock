"""Instance Fernet key and encrypted app-setting values.

The key lives at ``/config/.reeldock-settings.key`` (or ``REELDOCK_SETTINGS_KEY``).
If encrypted rows exist and the key is missing or corrupt, fail closed — never
mint a replacement key that would permanently lock out existing secrets.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SECRET_PREFIX = "enc:v1:"  # noqa: S105
DEFAULT_KEY_PATH = Path("/config/.reeldock-settings.key")
_ENV_KEY_NAME = "REELDOCK_SETTINGS_KEY"


class SecretStoreError(RuntimeError):
    """Raised when the instance settings key cannot be used safely."""


def _key_path() -> Path:
    override = os.environ.get("REELDOCK_SETTINGS_KEY_FILE", "").strip()
    if override:
        return Path(override)
    return DEFAULT_KEY_PATH


def is_encrypted_value(raw: str | None) -> bool:
    return raw is not None and raw.startswith(SECRET_PREFIX)


def _load_or_create_key(*, allow_create: bool) -> bytes:
    env_key = os.environ.get(_ENV_KEY_NAME, "").strip()
    if env_key:
        return env_key.encode("ascii")

    path = _key_path()
    if path.exists():
        data = path.read_bytes().strip()
        if not data:
            raise SecretStoreError(
                f"Settings key file {path} is empty. Restore the instance key "
                "from backup before starting ReelDock."
            )
        return data

    if not allow_create:
        raise SecretStoreError(
            f"Encrypted settings exist but the instance key is missing at {path}. "
            "Restore /config/.reeldock-settings.key (or set REELDOCK_SETTINGS_KEY). "
            "A new key was not generated."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        logger.warning("Could not set 0600 permissions on settings key file")
    return key


def get_fernet(*, allow_create: bool = True) -> Fernet:
    key = _load_or_create_key(allow_create=allow_create)
    try:
        return Fernet(key)
    except Exception as exc:
        raise SecretStoreError(
            "The instance settings key is corrupt or not a Fernet key. "
            "Restore the original key; a replacement would make existing "
            "encrypted settings unreadable."
        ) from exc


def hmac_key() -> bytes:
    """Key material for pairing-code HMACs (derived from the Fernet key)."""
    return _load_or_create_key(allow_create=True)


def encrypt_secret(plaintext: str) -> str:
    token = get_fernet(allow_create=True).encrypt(plaintext.encode("utf-8"))
    return f"{SECRET_PREFIX}{token.decode('ascii')}"


def decrypt_secret(stored: str) -> str:
    if not is_encrypted_value(stored):
        return stored
    token = stored[len(SECRET_PREFIX) :].encode("ascii")
    try:
        return get_fernet(allow_create=False).decrypt(token).decode("utf-8")
    except SecretStoreError:
        raise
    except InvalidToken as exc:
        raise SecretStoreError(
            "Could not decrypt a UI-managed secret. The instance settings key "
            "does not match this database. Restore the original key from backup."
        ) from exc
