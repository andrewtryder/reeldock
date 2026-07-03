"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine as _sync_create_engine
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# ---------------------------------------------------------------------------
# Async engine (FastAPI app)
# ---------------------------------------------------------------------------

_async_engine = None
_async_session_factory = None


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(
            settings.database_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(get_async_engine(), expire_on_commit=False)
    return _async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


def _alembic_config() -> Config:
    """Return Alembic config pointing at the project alembic.ini."""
    project_root = Path(__file__).resolve().parent.parent
    return Config(str(project_root / "alembic.ini"))


def _run_legacy_migrations(connection: Connection) -> None:
    """Apply pre-Alembic column additions for very old databases."""
    cursor = connection.execute(text("PRAGMA table_info(jobs)"))
    cols = [row[1] for row in cursor.fetchall()]

    new_cols = [
        ("progress", "INTEGER"),
        ("progress_percent", "FLOAT"),
        ("progress_eta", "VARCHAR(32)"),
        ("progress_speed", "VARCHAR(32)"),
        ("progress_label", "VARCHAR(64)"),
        ("output_file_size", "INTEGER"),
    ]

    for col_name, col_type in new_cols:
        if col_name not in cols:
            connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"))
    if "allow_reimport" not in cols:
        connection.execute(text("ALTER TABLE jobs ADD COLUMN allow_reimport BOOLEAN DEFAULT 0"))

    cursor_attempts = connection.execute(text("PRAGMA table_info(job_attempts)"))
    attempts_cols = [row[1] for row in cursor_attempts.fetchall()]

    if "artifact_metadata" not in attempts_cols:
        connection.execute(text("ALTER TABLE job_attempts ADD COLUMN artifact_metadata TEXT"))


def _run_migrations(connection: Connection, cfg: Config) -> None:
    """Run Alembic migrations, bootstrapping legacy databases when needed."""
    inspector = inspect(connection)
    has_alembic_version = inspector.has_table("alembic_version")
    has_jobs = inspector.has_table("jobs")

    if has_jobs and not has_alembic_version:
        _run_legacy_migrations(connection)
        command.stamp(cfg, "head")
        return

    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Apply Alembic migrations on startup."""
    engine = get_async_engine()
    cfg = _alembic_config()

    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations, cfg)


# ---------------------------------------------------------------------------
# Sync engine (RQ worker — no event loop)
# ---------------------------------------------------------------------------

_sync_engine = None
_sync_session_factory = None


def get_sync_engine() -> Engine:
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        _sync_engine = _sync_create_engine(
            settings.sync_database_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _sync_engine


def get_sync_session_factory() -> sessionmaker[Session]:
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(get_sync_engine(), expire_on_commit=False)
    return _sync_session_factory


def get_sync_db() -> Session:
    """Return a new sync session. Caller is responsible for closing."""
    return get_sync_session_factory()()
