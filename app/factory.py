"""FastAPI application factory."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.auth import attach_basic_auth
from app.config import get_settings, reload_settings
from app.db import init_db
from app.preflight import check_required_paths
from app.routes import register_routers
from app.routes.pages import STATIC_DIR, configure_templates

logger = logging.getLogger(__name__)


def _package_version() -> str:
    """Return the installed package version from pyproject.toml metadata."""
    try:
        return version("reeldock")
    except PackageNotFoundError:
        data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
        return str(data["project"]["version"])


def _fallback_ui_version(default_version: str) -> str:
    """Return a v-prefixed package version for display."""
    return default_version if default_version.startswith("v") else f"v{default_version}"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize DB on startup."""
    await init_db()
    reload_settings()
    logger.info("Database initialized")
    yield


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="reeldock",
        description="Selective YouTube → Audiobookshelf importer",
        version=_package_version(),
        lifespan=lifespan,
    )
    ui_version = _fallback_ui_version(app.version)
    app.state.ui_version = ui_version
    configure_templates(ui_version)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    attach_basic_auth(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        results = check_required_paths()
        all_ok = all(result.error is None for result in results)
        # Public probe only — detailed path diagnostics live on the
        # authenticated Diagnostics page (Basic Auth bypasses /ready for
        # Docker HEALTHCHECK, so do not leak filesystem paths here).
        return JSONResponse(
            content={"status": "ready" if all_ok else "not_ready"},
            status_code=200 if all_ok else 503,
        )

    register_routers(app)
    return app
