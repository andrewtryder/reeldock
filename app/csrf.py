"""Signed CSRF tokens for Web UI POSTs that sit behind Basic Auth."""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.secret_store import hmac_key

_SALT = "reeldock-settings-csrf"
_MAX_AGE_SECONDS = 8 * 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(hmac_key(), salt=_SALT)


def issue_csrf_token() -> str:
    return _serializer().dumps("ok")


def validate_csrf_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        return bool(_serializer().loads(token, max_age=_MAX_AGE_SECONDS) == "ok")
    except BadSignature, SignatureExpired, Exception:
        return False
