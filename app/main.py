"""FastAPI application entry point."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.factory import create_app

__all__ = ["create_app"]

# Lazily constructed so `from app.main import create_app` in tests does not
# require a fully valid runtime `.env` at import time. Uvicorn still loads
# `app.main:app` via __getattr__.
_app = None


def __getattr__(name: str) -> Any:  # noqa: ANN401
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "app.main:app",
        host=s.app_host,
        port=s.app_port,
        reload=False,
    )
