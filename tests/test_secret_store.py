"""Fernet settings key and encrypted UI secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.secret_store import (
    SECRET_PREFIX,
    SecretStoreError,
    decrypt_secret,
    encrypt_secret,
    is_encrypted_value,
)
from cryptography.fernet import Fernet
from sqlalchemy import select


def test_hmac_subkeys_differ_from_fernet_and_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("REELDOCK_SETTINGS_KEY", key.decode("ascii"))
    from app.secret_store import CSRF_HMAC_INFO, derive_hmac_key, hmac_key

    pairing = hmac_key()
    csrf = derive_hmac_key(CSRF_HMAC_INFO)
    assert pairing != csrf
    assert pairing != key
    assert csrf != key
    assert len(pairing) == 32
    assert hmac_key() == pairing


def test_encrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELDOCK_SETTINGS_KEY", Fernet.generate_key().decode("ascii"))
    token = encrypt_secret("s3cret")
    assert token.startswith(SECRET_PREFIX)
    assert is_encrypted_value(token)
    assert decrypt_secret(token) == "s3cret"


def test_missing_key_with_ciphertext_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("REELDOCK_SETTINGS_KEY", key.decode("ascii"))
    token = encrypt_secret("hidden")
    monkeypatch.delenv("REELDOCK_SETTINGS_KEY")
    monkeypatch.setenv("REELDOCK_SETTINGS_KEY_FILE", str(tmp_path / "missing.key"))
    with pytest.raises(SecretStoreError, match="missing"):
        decrypt_secret(token)


def test_db_secret_is_ciphertext_not_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import get_sync_session_factory, init_db
    from app.models import AppSetting

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'app.db'}")
    monkeypatch.delenv("ABS_API_TOKEN", raising=False)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())

    save_settings({"abs_api_token": "super-secret-token"})
    with get_sync_session_factory()() as session:
        row = session.scalar(select(AppSetting).where(AppSetting.key == "abs_api_token"))
        assert row is not None
        assert row.value is not None
        assert row.value.startswith(SECRET_PREFIX)
        assert "super-secret-token" not in row.value

    settings = reload_settings()
    assert settings.abs_api_token == "super-secret-token"


def test_blank_secret_keeps_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'app.db'}")
    monkeypatch.delenv("ABS_API_TOKEN", raising=False)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())

    save_settings({"abs_api_token": "keep-me"})
    save_settings({"abs_api_token": ""})
    assert reload_settings().abs_api_token == "keep-me"


def test_reset_clears_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, reset_setting, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'app.db'}")
    monkeypatch.delenv("ABS_API_TOKEN", raising=False)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())

    save_settings({"abs_api_token": "wipe-me"})
    reset_setting("abs_api_token")
    assert reload_settings().abs_api_token is None


def test_worker_reload_sees_new_db_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.config import reload_settings, save_settings
    from app.db import init_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'app.db'}")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())

    assert reload_settings().dry_run is False
    save_settings({"dry_run": "true"})
    worker_view = reload_settings()
    assert worker_view.dry_run is True
