"""One-use WebSocket tickets for paired extension clients."""

from __future__ import annotations

import hashlib
import logging
import secrets

from app.queue import RedisCommands

logger = logging.getLogger(__name__)

TICKET_TTL_SECONDS = 60
TICKET_PREFIX = "reeldock:ws-ticket:"
REVOKED_PREFIX = "reeldock:device-revoked:"


def _ticket_key(ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return f"{TICKET_PREFIX}{digest}"


def issue_ws_ticket(redis: RedisCommands, *, job_id: str, device_id: str) -> str:
    ticket = secrets.token_urlsafe(24)
    redis.setex(_ticket_key(ticket), TICKET_TTL_SECONDS, f"{job_id}:{device_id}")
    return ticket


def redeem_ws_ticket(redis: RedisCommands, ticket: str) -> tuple[str, str] | None:
    key = _ticket_key(ticket)
    try:
        raw = redis.getdel(key)
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        job_id, _, device_id = text.partition(":")
        if not job_id or not device_id:
            return None
        return job_id, device_id
    except Exception:
        logger.warning("WebSocket ticket store unavailable")
        return None


def mark_device_revoked(redis: RedisCommands, device_id: str) -> None:
    try:
        redis.setex(f"{REVOKED_PREFIX}{device_id}", 86400, "1")
    except Exception:
        logger.warning("Could not publish device revocation")


def is_device_revoked(redis: RedisCommands, device_id: str) -> bool:
    try:
        return bool(redis.get(f"{REVOKED_PREFIX}{device_id}"))
    except Exception:
        return False
