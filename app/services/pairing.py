"""Browser pairing codes and per-device tokens."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import ExtensionDevice, ExtensionPairingCode
from app.queue import RedisCommands
from app.secret_store import hmac_key

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=5)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIR_RATE_LIMIT = 10
PAIR_RATE_WINDOW_SECONDS = 300
LAST_SEEN_THROTTLE = timedelta(seconds=60)
DEVICE_TOKEN_PREFIX = "rdx_"  # noqa: S105


class PairingError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def generate_pairing_code() -> str:
    left = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    return f"RDK-{left}-{right}"


def normalize_pairing_code(raw: str) -> str:
    compact = "".join(ch for ch in (raw or "").strip().upper() if ch.isalnum() or ch == "-")
    if compact.startswith("RDK") and "-" not in compact[3:]:
        rest = compact[3:]
        if len(rest) == 8:
            compact = f"RDK-{rest[:4]}-{rest[4:]}"
    return compact


def pairing_code_hmac(code: str) -> str:
    digest = hmac.new(hmac_key(), normalize_pairing_code(code).encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_device_token() -> str:
    return f"{DEVICE_TOKEN_PREFIX}{secrets.token_hex(32)}"


def _utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def purge_expired_pairing_codes(session: Session) -> None:
    """Drop unused pairing rows whose TTL has already elapsed."""
    session.execute(
        delete(ExtensionPairingCode).where(
            ExtensionPairingCode.consumed_at.is_(None),
            ExtensionPairingCode.expires_at <= _utc_now(),
        )
    )


def create_pairing_code(
    session: Session,
    *,
    created_by: str | None = None,
    user_agent: str | None = None,
) -> tuple[ExtensionPairingCode, str]:
    purge_expired_pairing_codes(session)
    code = generate_pairing_code()
    now = _utc_now()
    row = ExtensionPairingCode(
        code_hmac=pairing_code_hmac(code),
        expires_at=now + CODE_TTL,
        created_by=created_by,
        user_agent=(user_agent or "")[:256] or None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, code


def _raise_consume_failure(session: Session, code_hash: str) -> None:
    row = session.scalar(
        select(ExtensionPairingCode).where(ExtensionPairingCode.code_hmac == code_hash)
    )
    if row is None:
        raise PairingError("Invalid pairing code", status_code=401)
    if row.consumed_at is not None:
        raise PairingError("Pairing code already used", status_code=401)
    if _aware(row.expires_at) <= datetime.now(tz=UTC):
        raise PairingError("Pairing code expired", status_code=401)
    raise PairingError("Invalid pairing code", status_code=401)


def consume_pairing_code(
    session: Session,
    *,
    pairing_code: str,
    device_name: str,
    browser: str | None = None,
    platform: str | None = None,
) -> tuple[ExtensionDevice, str]:
    normalized = normalize_pairing_code(pairing_code)
    if not normalized.startswith("RDK-") or len(normalized) != 13:
        raise PairingError("Invalid pairing code")

    now = _utc_now()
    code_hash = pairing_code_hmac(normalized)
    claimed = session.execute(
        update(ExtensionPairingCode)
        .where(
            ExtensionPairingCode.code_hmac == code_hash,
            ExtensionPairingCode.consumed_at.is_(None),
            ExtensionPairingCode.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session="fetch")
    )
    if int(getattr(claimed, "rowcount", 0) or 0) != 1:
        _raise_consume_failure(session, code_hash)

    token = mint_device_token()
    name = (device_name or "Browser").strip()[:80] or "Browser"
    device = ExtensionDevice(
        display_name=name,
        browser=(browser or "")[:64] or None,
        platform=(platform or "")[:64] or None,
        token_hash=hash_device_token(token),
        token_prefix=token[4:12],
        last_seen_at=now,
    )
    session.add(device)
    purge_expired_pairing_codes(session)
    session.commit()
    session.refresh(device)
    return device, token


def lookup_device_by_token(session: Session, token: str) -> ExtensionDevice | None:
    if not token or not token.startswith(DEVICE_TOKEN_PREFIX):
        return None
    device = session.scalar(
        select(ExtensionDevice).where(ExtensionDevice.token_hash == hash_device_token(token))
    )
    return device


def touch_last_seen(session: Session, device: ExtensionDevice) -> None:
    now = datetime.now(tz=UTC)
    last = device.last_seen_at
    if last is None or now - _aware(last) >= LAST_SEEN_THROTTLE:
        device.last_seen_at = now
        session.commit()


def revoke_device(session: Session, device: ExtensionDevice) -> None:
    if device.revoked_at is None:
        device.revoked_at = datetime.now(tz=UTC)
        session.commit()


def revoke_all_devices(session: Session) -> int:
    now = datetime.now(tz=UTC)
    count = 0
    for device in session.scalars(select(ExtensionDevice)).all():
        if device.revoked_at is None:
            device.revoked_at = now
            count += 1
    session.commit()
    return count


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int


def check_pair_rate_limit(redis: RedisCommands, source: str) -> RateLimitResult:
    """Increment failure counter. Call after a failed pair attempt."""
    key = f"reeldock:pair:fail:{source}"
    try:
        count = int(redis.incr(key))
        if count == 1:
            redis.expire(key, PAIR_RATE_WINDOW_SECONDS)
        remaining = max(0, PAIR_RATE_LIMIT - count)
        return RateLimitResult(allowed=count <= PAIR_RATE_LIMIT, remaining=remaining)
    except Exception:
        logger.warning("Pairing rate limiter unavailable; failing closed")
        return RateLimitResult(allowed=False, remaining=0)


def pair_failures_blocked(redis: RedisCommands, source: str) -> bool:
    key = f"reeldock:pair:fail:{source}"
    try:
        raw = redis.get(key)
        if raw is None:
            return False
        return int(raw) >= PAIR_RATE_LIMIT
    except Exception:
        logger.warning("Pairing rate limiter unavailable; failing closed")
        return True
