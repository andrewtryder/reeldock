"""Pairing codes, device tokens, CSRF, and rate limits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.factory import create_app
from app.services.pairing import (
    consume_pairing_code,
    create_pairing_code,
    hash_device_token,
    normalize_pairing_code,
    pairing_code_hmac,
)
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def incr(self, key: str) -> int:
        value = int(self.data.get(key, 0)) + 1
        self.data[key] = value
        return value

    def expire(self, key: str, _seconds: int) -> None:
        return None

    def get(self, key: str) -> object | None:
        return self.data.get(key)

    def setex(self, key: str, _ttl: int, value: object) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def pairing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.db import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'pair.db'}")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.delenv("EXTENSION_API_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    monkeypatch.setattr(cfg_module, "_parse_dotenv_keys", lambda: set())
    cfg_module._settings = None
    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())
    fake = FakeRedis()
    monkeypatch.setattr("app.queue.get_redis", lambda: fake)
    yield fake
    cfg_module._settings = None


def _csrf(client: TestClient) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text)
    assert match
    return match.group(1)


def test_pairing_code_hashed_at_rest(pairing_env: FakeRedis) -> None:
    from app.db import get_sync_session_factory
    from app.models import ExtensionPairingCode
    from sqlalchemy import select

    with get_sync_session_factory()() as session:
        row, code = create_pairing_code(session, created_by="admin")
        stored = session.scalar(
            select(ExtensionPairingCode).where(ExtensionPairingCode.id == row.id)
        )
        assert stored is not None
        assert code not in (stored.code_hmac or "")
        assert stored.code_hmac == pairing_code_hmac(code)
        assert normalize_pairing_code(code).startswith("RDK-")


def test_pair_success_and_single_use(pairing_env: FakeRedis) -> None:
    from app.db import get_sync_session_factory
    from app.models import ExtensionDevice
    from sqlalchemy import select

    with get_sync_session_factory()() as session:
        _row, code = create_pairing_code(session)

    with TestClient(create_app()) as client:
        first = client.post(
            "/api/extension/pair",
            json={"pairing_code": code, "device_name": "Test Firefox"},
        )
        assert first.status_code == 200
        body = first.json()
        assert body["device_token"].startswith("rdx_")
        assert body["api_version"] == 1
        assert "destinations" in body["supports"]

        second = client.post(
            "/api/extension/pair",
            json={"pairing_code": code, "device_name": "Other"},
        )
        assert second.status_code == 401

        status = client.get(
            "/api/extension/status",
            headers={"Authorization": f"Bearer {body['device_token']}"},
        )
        assert status.status_code == 200
        assert status.json()["auth_kind"] == "device"

    with get_sync_session_factory()() as session:
        device = session.scalar(select(ExtensionDevice))
        assert device is not None
        assert device.token_hash == hash_device_token(body["device_token"])
        assert body["device_token"] not in device.token_hash


def test_pair_wrong_code_and_rate_limit(pairing_env: FakeRedis) -> None:
    with TestClient(create_app()) as client:
        for _ in range(10):
            response = client.post(
                "/api/extension/pair",
                json={"pairing_code": "RDK-ZZZZ-ZZZZ", "device_name": "X"},
            )
            assert response.status_code in {401, 429}
        blocked = client.post(
            "/api/extension/pair",
            json={"pairing_code": "RDK-ZZZZ-ZZZZ", "device_name": "X"},
        )
        assert blocked.status_code == 429


def test_pair_disabled_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.db import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'off.db'}")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())
    with TestClient(create_app()) as client:
        assert (
            client.post(
                "/api/extension/pair",
                json={"pairing_code": "RDK-AAAA-BBBB", "device_name": "X"},
            ).status_code
            == 404
        )


def test_revoke_device_then_401(pairing_env: FakeRedis) -> None:
    from app.db import get_sync_session_factory

    with get_sync_session_factory()() as session:
        _row, code = create_pairing_code(session)

    with TestClient(create_app()) as client:
        token = client.post(
            "/api/extension/pair",
            json={"pairing_code": code, "device_name": "Revoke Me"},
        ).json()["device_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/extension/status", headers=headers).status_code == 200
        assert client.post("/api/extension/devices/me/revoke", headers=headers).status_code == 200
        assert client.get("/api/extension/status", headers=headers).status_code == 401


def test_legacy_token_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.config as cfg_module
    import app.db as db_module
    from app.db import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "true")
    monkeypatch.setenv("EXTENSION_API_TOKEN", "legacy-shared-token")
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    cfg_module._settings = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None
    asyncio.run(init_db())
    with TestClient(create_app()) as client:
        status = client.get(
            "/api/extension/status",
            headers={"Authorization": "Bearer legacy-shared-token"},
        )
        assert status.status_code == 200
        assert status.json()["auth_kind"] == "legacy"


def test_pair_code_create_requires_csrf(pairing_env: FakeRedis) -> None:
    with TestClient(create_app()) as client:
        denied = client.post("/settings/extension/pair-code", data={})
        assert denied.status_code == 403
        ok = client.post(
            "/settings/extension/pair-code",
            data={"csrf_token": _csrf(client)},
        )
        assert ok.status_code == 200
        assert "RDK-" in ok.text


def test_expired_code_rejected(pairing_env: FakeRedis) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db import get_sync_session_factory
    from app.services.pairing import PairingError

    with get_sync_session_factory()() as session:
        row, code = create_pairing_code(session)
        row.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        session.commit()
        with pytest.raises(PairingError, match="expired"):
            consume_pairing_code(session, pairing_code=code, device_name="Late")


def test_ws_ticket_for_device(pairing_env: FakeRedis) -> None:
    from app.db import get_sync_session_factory

    with get_sync_session_factory()() as session:
        _row, code = create_pairing_code(session)

    with TestClient(create_app()) as client:
        token = client.post(
            "/api/extension/pair",
            json={"pairing_code": code, "device_name": "WS"},
        ).json()["device_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ticket = client.post(
            "/api/extension/ws-ticket",
            headers=headers,
            json={"job_id": "job-1"},
        )
        assert ticket.status_code == 200
        assert ticket.json()["ticket"]
        # Device tokens are rejected on ?token=
        # (ticket path is covered when a real job exists)
