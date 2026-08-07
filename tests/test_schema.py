"""Tests for Alembic-backed database schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from app.db import init_db

_MINIMAL_JOBS_DDL = """
CREATE TABLE jobs (
    id VARCHAR(36) PRIMARY KEY,
    url TEXT NOT NULL,
    status VARCHAR(14) NOT NULL,
    collision_mode VARCHAR(20) NOT NULL,
    embed_metadata BOOLEAN NOT NULL,
    embed_thumbnail BOOLEAN NOT NULL,
    embed_chapters BOOLEAN NOT NULL,
    trigger_abs_scan BOOLEAN NOT NULL,
    attempts INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _reset_db_engines() -> None:
    import app.db as db_module

    db_module._async_engine = None
    db_module._async_session_factory = None
    db_module._sync_engine = None
    db_module._sync_session_factory = None


@pytest.fixture
def schema_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolated SQLite database for schema tests."""
    db_path = tmp_path / "schema.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("EXTENSION_API_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("REELDOCK_FETCH_UI_VERSION", "0")
    import app.config as cfg_module

    cfg_module._settings = None
    _reset_db_engines()
    return db_path


@pytest.mark.asyncio
async def test_init_db_creates_schema_on_fresh_database(schema_db: Path):
    await init_db()

    with sqlite3.connect(schema_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "jobs",
            "imported_videos",
            "job_attempts",
            "app_settings",
            "import_batches",
            "alembic_version",
        } <= tables

        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None
        assert version[0] == "0001_baseline"

        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "progress" in jobs_cols
        assert "allow_reimport" in jobs_cols
        assert "batch_id" in jobs_cols
        assert "sponsorblock_remove" in jobs_cols


@pytest.mark.asyncio
async def test_init_db_stamps_legacy_database(schema_db: Path):
    with sqlite3.connect(schema_db) as conn:
        conn.executescript(
            f"""
            {_MINIMAL_JOBS_DDL}
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

    with sqlite3.connect(schema_db) as conn:
        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "progress" in jobs_cols
        assert "allow_reimport" in jobs_cols
        assert "batch_id" in jobs_cols
        assert "sponsorblock_remove" in jobs_cols

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "import_batches" in tables
        assert "app_settings" in tables
        assert "alembic_version" in tables
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version[0] == "0001_baseline"


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_revision", ["f2b6d4e83a50", "c7a3e9f12b40"])
async def test_init_db_stamps_retired_alembic_revision(schema_db: Path, retired_revision: str):
    with sqlite3.connect(schema_db) as conn:
        conn.executescript(
            f"""
            {_MINIMAL_JOBS_DDL}
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL
            );
            INSERT INTO alembic_version (version_num) VALUES ('{retired_revision}');
            """
        )
        conn.commit()

    await init_db()

    with sqlite3.connect(schema_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "import_batches" in tables
        assert "app_settings" in tables
        assert "alembic_version" in tables
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version[0] == "0001_baseline"
        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "batch_id" in jobs_cols
        assert "sponsorblock_remove" in jobs_cols


@pytest.mark.asyncio
async def test_init_db_rejects_unknown_alembic_revision(schema_db: Path):
    with sqlite3.connect(schema_db) as conn:
        conn.executescript(
            f"""
            {_MINIMAL_JOBS_DDL}
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL
            );
            INSERT INTO alembic_version (version_num) VALUES ('deadbeef');
            """
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="Unknown alembic revision 'deadbeef'"):
        await init_db()


@pytest.mark.asyncio
async def test_init_db_is_idempotent(schema_db: Path):
    await init_db()
    await init_db()

    with sqlite3.connect(schema_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "jobs" in tables
        assert "import_batches" in tables
        assert "alembic_version" in tables


@pytest.mark.asyncio
async def test_init_db_preserves_extra_columns_from_older_builds(schema_db: Path):
    with sqlite3.connect(schema_db) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id VARCHAR(36) PRIMARY KEY,
                url TEXT NOT NULL,
                status VARCHAR(14) NOT NULL,
                collision_mode VARCHAR(20) NOT NULL,
                embed_metadata BOOLEAN NOT NULL,
                embed_thumbnail BOOLEAN NOT NULL,
                embed_chapters BOOLEAN NOT NULL,
                trigger_abs_scan BOOLEAN NOT NULL,
                attempts INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sponsorblock_mark_chapters BOOLEAN NOT NULL DEFAULT 0
            );
            """
        )
        conn.commit()

    await init_db()

    with sqlite3.connect(schema_db) as conn:
        jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "sponsorblock_mark_chapters" in jobs_cols
        assert "batch_id" in jobs_cols
        assert "alembic_version" in {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
