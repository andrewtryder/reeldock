"""Tests for Alembic-driven database initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db import init_db


def _reset_db_engines() -> None:
    import app.db as db_module

    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


@pytest.fixture
def migration_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolated SQLite database for migration tests."""
    db_path = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    _reset_db_engines()
    return db_path


@pytest.mark.asyncio
async def test_init_db_creates_schema_on_fresh_database(migration_db: Path):
    await init_db()

    with sqlite3.connect(migration_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"jobs", "imported_videos", "job_attempts", "alembic_version"} <= tables

        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None
        assert version[0] == "b4e8f1a92d10"

        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "progress" in jobs_cols
        assert "allow_reimport" in jobs_cols

        attempts_cols = {row[1] for row in conn.execute("PRAGMA table_info(job_attempts)")}
        assert "artifact_metadata" in attempts_cols


@pytest.mark.asyncio
async def test_init_db_bootstraps_legacy_database_without_alembic_version(migration_db: Path):
    """Pre-Alembic databases are upgraded in place and stamped at head."""
    with sqlite3.connect(migration_db) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id VARCHAR(36) PRIMARY KEY,
                url TEXT NOT NULL,
                video_id VARCHAR(64),
                source_title TEXT,
                status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE job_attempts (
                id VARCHAR(36) PRIMARY KEY,
                job_id VARCHAR(36) NOT NULL,
                attempt_number INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL
            );
            CREATE TABLE imported_videos (
                video_id VARCHAR(64) PRIMARY KEY,
                job_id VARCHAR(36),
                source_url TEXT,
                source_title TEXT,
                imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()

    await init_db()

    with sqlite3.connect(migration_db) as conn:
        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "progress" in jobs_cols
        assert "allow_reimport" in jobs_cols

        attempts_cols = {row[1] for row in conn.execute("PRAGMA table_info(job_attempts)")}
        assert "artifact_metadata" in attempts_cols

        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None
        assert version[0] == "b4e8f1a92d10"


@pytest.mark.asyncio
async def test_init_db_is_idempotent(migration_db: Path):
    await init_db()
    await init_db()

    with sqlite3.connect(migration_db) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None


def test_alembic_cli_upgrade_head(migration_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Alembic CLI can upgrade a fresh database using app settings."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{migration_db}")
    _reset_db_engines()

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")

    with sqlite3.connect(migration_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "jobs" in tables
        assert "alembic_version" in tables
