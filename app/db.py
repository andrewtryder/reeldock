"""Database engine and session factory."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, DateTime, Integer, String, Text, inspect, text
from sqlalchemy import create_engine as _sync_create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.schema import Column

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

_BASELINE_REVISION = "0001_baseline"
_ROOT = Path(__file__).resolve().parents[1]

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


def _default_sql_for_column(column: Column[object]) -> str:
    """Return a SQLite DEFAULT clause for additive columns on existing tables."""
    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        value = getattr(default, "arg", None)
        if isinstance(value, bool):
            return f" DEFAULT {int(value)}"
        if isinstance(value, int | float):
            return f" DEFAULT {value}"
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f" DEFAULT '{escaped}'"

    if column.nullable:
        return ""

    if isinstance(column.type, Boolean):
        return " DEFAULT 0"
    if isinstance(column.type, Integer):
        return " DEFAULT 0"
    if isinstance(column.type, DateTime):
        return " DEFAULT CURRENT_TIMESTAMP"
    if isinstance(column.type, String | Text):
        return " DEFAULT ''"
    return ""


def _add_missing_columns(connection: Connection) -> None:
    """One-time additive sync used only when stamping a pre-Alembic database."""
    inspector = inspect(connection)
    dialect = connection.dialect
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            type_sql = column.type.compile(dialect=dialect)
            default_sql = _default_sql_for_column(column)
            connection.execute(
                text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}{default_sql}")
            )
            logger.info("Added column %s.%s", table.name, column.name)


def _alembic_config() -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
    return cfg


def _is_legacy_unversioned(connection: Connection) -> bool:
    inspector = inspect(connection)
    return inspector.has_table("jobs") and not inspector.has_table("alembic_version")


def run_migrations() -> None:
    """Apply Alembic migrations, stamping pre-Alembic databases first."""
    engine = get_sync_engine()
    cfg = _alembic_config()
    legacy = False

    with engine.begin() as connection:
        legacy = _is_legacy_unversioned(connection)
        if legacy:
            # Bring a pre-Alembic SQLite DB up to the current model shape, then
            # stamp the baseline so future revisions use Alembic only.
            Base.metadata.create_all(bind=connection)
            _add_missing_columns(connection)
            logger.info("Detected legacy unversioned database; preparing Alembic stamp")

    if legacy:
        command.stamp(cfg, _BASELINE_REVISION)
        logger.info("Stamped legacy database at %s", _BASELINE_REVISION)

    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied (head)")


async def init_db() -> None:
    """Create or update the database schema via Alembic."""
    try:
        # Alembic uses the sync engine; ensure it exists before upgrading.
        get_sync_engine()
        run_migrations()
    except Exception as exc:
        print(f"Database schema init failed: {exc}", file=sys.stderr, flush=True)
        logger.exception("Database schema init failed")
        raise


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
