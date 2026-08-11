"""Authentication middleware and dependencies."""

from __future__ import annotations

import base64
import contextlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import Settings, get_settings


@dataclass
class ExtensionPrincipal:
    """Authenticated extension caller (device token or legacy shared token)."""

    settings: Settings
    auth_kind: Literal["device", "legacy"]
    device_id: str | None = None
    device_name: str | None = None

    def __getattr__(self, name: str) -> object:
        return getattr(self.settings, name)


def _extract_bearer_or_header(headers: Mapping[str, str]) -> str | None:
    token = None
    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    x_token = headers.get("X-REELDOCK-Token")
    if x_token:
        token = x_token
    return token


def _tokens_match(given: str, expected: str | None) -> bool:
    if not expected:
        return False
    if len(given) != len(expected):
        return False
    return secrets.compare_digest(given, expected)


def _authenticate_extension_token(token: str | None, cfg: Settings) -> ExtensionPrincipal:
    if not cfg.extension_api_enabled:
        raise HTTPException(status_code=404, detail="Extension API not enabled")
    if not token:
        raise HTTPException(status_code=401, detail="Invalid extension API token")

    from app.db import get_sync_session_factory
    from app.services.pairing import lookup_device_by_token, touch_last_seen

    factory = get_sync_session_factory()
    with factory() as session:
        device = lookup_device_by_token(session, token)
        if device is not None:
            if device.revoked_at is not None:
                raise HTTPException(status_code=401, detail="Device token revoked")
            touch_last_seen(session, device)
            return ExtensionPrincipal(
                settings=cfg,
                auth_kind="device",
                device_id=device.id,
                device_name=device.display_name,
            )

    if _tokens_match(token, cfg.extension_api_token):
        return ExtensionPrincipal(settings=cfg, auth_kind="legacy")

    raise HTTPException(status_code=401, detail="Invalid extension API token")


def extension_api_auth(
    request: Request, cfg: Annotated[Settings, Depends(get_settings)]
) -> ExtensionPrincipal:
    """Authorize an extension HTTP request via device token or legacy token."""
    return _authenticate_extension_token(_extract_bearer_or_header(request.headers), cfg)


ExtensionAuthDep = Annotated[ExtensionPrincipal, Depends(extension_api_auth)]


async def validate_websocket_token(
    job_id: str,
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtensionPrincipal | None:
    """Validate a WebSocket via one-use ticket (preferred) or legacy ?token=.

    Returns the principal for ticket/legacy auth. Ticket redeem is one-use.
    """
    if not settings.extension_api_enabled:
        raise HTTPException(status_code=404, detail="Extension API not enabled")

    ticket = websocket.query_params.get("ticket")
    if ticket:
        from app.queue import get_redis
        from app.services.ws_tickets import is_device_revoked, redeem_ws_ticket

        redeemed = redeem_ws_ticket(get_redis(), ticket)
        if redeemed is None:
            raise HTTPException(status_code=401, detail="Invalid or expired WebSocket ticket")
        ticket_job_id, device_id = redeemed
        if ticket_job_id != job_id:
            raise HTTPException(status_code=401, detail="Invalid or expired WebSocket ticket")
        if is_device_revoked(get_redis(), device_id):
            raise HTTPException(status_code=401, detail="Device token revoked")
        return ExtensionPrincipal(
            settings=settings,
            auth_kind="device",
            device_id=device_id,
        )

    token = _extract_bearer_or_header(websocket.headers)
    query_token = websocket.query_params.get("token")
    if query_token:
        token = query_token

    # Legacy shared token only — device tokens must use ?ticket=.
    if token and _tokens_match(token, settings.extension_api_token):
        return ExtensionPrincipal(settings=settings, auth_kind="legacy")

    if token and token.startswith("rdx_"):
        raise HTTPException(
            status_code=401,
            detail="Paired devices must use a short-lived WebSocket ticket",
        )

    raise HTTPException(status_code=401, detail="Invalid extension API token")


def attach_basic_auth(app: FastAPI) -> None:
    """Add HTTP Basic Auth middleware that reads current settings per request."""

    class BasicAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            settings = get_settings()
            if not settings.auth_enabled:
                return await call_next(request)

            path = request.url.path
            upgrade = request.headers.get("upgrade", "").lower()
            ws_upgrade = path.startswith("/api/ws/") and upgrade == "websocket"
            if path in ("/health", "/ready") or path.startswith("/api/extension/") or ws_upgrade:
                return await call_next(request)

            expected_user = settings.auth_username or ""
            expected_pass = settings.auth_password or ""

            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Basic "):
                with contextlib.suppress(Exception):
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    user, _, pwd = decoded.partition(":")
                    if secrets.compare_digest(user, expected_user) and secrets.compare_digest(
                        pwd, expected_pass
                    ):
                        return await call_next(request)

            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="reeldock"'},
            )

    app.add_middleware(BasicAuthMiddleware)
