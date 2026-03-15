"""
backend/database.py

Async SQLite connection pool and schema management.

Provides:
  - AsyncDB: thin wrapper around aiosqlite with typed query helpers
  - get_db():  FastAPI dependency that yields an AsyncDB instance
  - create_tables(): idempotent schema migration (safe to call on every startup)

All datetime values stored as ISO 8601 UTC strings: YYYY-MM-DDTHH:MM:SSZ
All UUIDs stored as TEXT.

Schema tables:
  config          — single-user credential store (key/value)
  jobs            — acquisition job lifecycle
  custom_tracks   — user-defined tag metadata
  custom_tracks_fts — FTS5 virtual table for trigram fuzzy search

Patterns:
  - Never import os.environ here — settings come from backend.config
  - Never open a connection outside get_db() in application code
  - All writes go through execute() — never raw aiosqlite calls in routers
  - Row factory is sqlite3.Row so results support both index and key access
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema — single source of truth
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- -------------------------------------------------------------------------
-- config: single-user credentials and app settings (key/value store)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- -------------------------------------------------------------------------
-- jobs: acquisition job lifecycle
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,           -- UUID v4
    status        TEXT NOT NULL               -- see JobStatusEnum
                    CHECK(status IN (
                        'pending',
                        'downloading',
                        'tagging',
                        'confirmed',
                        'error'
                    )),
    youtube_id    TEXT NOT NULL,
    title_hint    TEXT,
    file_path     TEXT,                       -- set after download_complete
    library_path  TEXT,                       -- set after file move
    navidrome_id  TEXT,                       -- set after library_ready
    percent       REAL,                       -- 0.0–100.0, updated during download
    error_message TEXT,                       -- set on job_error
    created_at    TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at
    ON jobs(created_at);

-- Keep updated_at current on every write
CREATE TRIGGER IF NOT EXISTS jobs_updated_at
    AFTER UPDATE ON jobs
    BEGIN
        UPDATE jobs
        SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = NEW.id;
    END;

-- -------------------------------------------------------------------------
-- custom_tracks: user-defined tag metadata persisted for future suggestions
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS custom_tracks (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    artist       TEXT,
    album        TEXT,
    year         INTEGER,
    genre        TEXT,
    source_query TEXT,          -- original search query or URL that produced this track
    youtube_id   TEXT,
    created_at   TEXT NOT NULL
                   DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- -------------------------------------------------------------------------
-- custom_tracks_fts: FTS5 trigram virtual table for fuzzy suggestions
-- Kept in sync with custom_tracks via triggers below.
-- -------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS custom_tracks_fts
    USING fts5(
        title,
        artist,
        album,
        source_query,
        content=custom_tracks,
        tokenize='trigram'
    );

-- Sync triggers: INSERT / UPDATE / DELETE on custom_tracks → fts index
CREATE TRIGGER IF NOT EXISTS custom_tracks_fts_insert
    AFTER INSERT ON custom_tracks
    BEGIN
        INSERT INTO custom_tracks_fts(rowid, title, artist, album, source_query)
        VALUES (NEW.id, NEW.title, NEW.artist, NEW.album, NEW.source_query);
    END;

CREATE TRIGGER IF NOT EXISTS custom_tracks_fts_update
    AFTER UPDATE ON custom_tracks
    BEGIN
        UPDATE custom_tracks_fts
        SET title        = NEW.title,
            artist       = NEW.artist,
            album        = NEW.album,
            source_query = NEW.source_query
        WHERE rowid = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS custom_tracks_fts_delete
    AFTER DELETE ON custom_tracks
    BEGIN
        DELETE FROM custom_tracks_fts WHERE rowid = OLD.id;
    END;
"""


# ---------------------------------------------------------------------------
# AsyncDB
# ---------------------------------------------------------------------------


class AsyncDB:
    """
    Thin async wrapper around an aiosqlite connection.

    Lifecycle:
        db = AsyncDB("/data/custom_metadata.db")
        await db.connect()
        await db.create_tables()
        # ... use db ...
        await db.close()

    In tests, the `db` fixture in conftest.py handles this lifecycle.
    In production, get_db() handles it via FastAPI's lifespan.

    Query helpers:
        await db.execute(sql, params)          — INSERT / UPDATE / DELETE
        await db.fetchone(sql, params)         — SELECT returning one row or None
        await db.fetchall(sql, params)         — SELECT returning list of rows
        await db.fetchval(sql, params)         — SELECT returning a single scalar
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection. Must be called before any query."""
        self._conn = await aiosqlite.connect(self._path)
        # Use sqlite3.Row so results support both index and column-name access.
        self._conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency (multiple readers, one writer).
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign key constraints.
        await self._conn.execute("PRAGMA foreign_keys=ON")
        logger.debug("database_connected", path=self._path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.debug("database_closed", path=self._path)

    async def create_tables(self) -> None:
        """
        Run the schema SQL. Safe to call on every startup — all statements
        use CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
        CREATE TRIGGER IF NOT EXISTS, so re-running is always idempotent.
        """
        self._assert_connected()
        await self._conn.executescript(_SCHEMA_SQL)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]
        logger.info("database_schema_ready", path=self._path)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> int:
        """
        Execute a write statement (INSERT, UPDATE, DELETE).
        Returns the lastrowid for INSERT statements, or rowcount for others.
        Commits automatically.
        """
        self._assert_connected()
        cursor = await self._conn.execute(sql, params)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]
        return cursor.lastrowid or cursor.rowcount

    async def fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> sqlite3.Row | None:
        """
        Execute a SELECT and return the first row, or None if no rows match.

        Usage:
            row = await db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if row:
                status = row["status"]
        """
        self._assert_connected()
        cursor = await self._conn.execute(sql, params)  # type: ignore[union-attr]
        return await cursor.fetchone()

    async def fetchall(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> list[sqlite3.Row]:
        """
        Execute a SELECT and return all matching rows as a list.
        Returns an empty list (not None) when no rows match.

        Usage:
            rows = await db.fetchall("SELECT * FROM jobs WHERE status = ?", ("pending",))
            for row in rows:
                print(row["id"], row["status"])
        """
        self._assert_connected()
        cursor = await self._conn.execute(sql, params)  # type: ignore[union-attr]
        return await cursor.fetchall()

    async def fetchval(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> Any:
        """
        Execute a SELECT and return the first column of the first row as a
        plain Python value, or None if no rows match.

        Usage:
            count = await db.fetchval("SELECT COUNT(*) FROM jobs WHERE status = ?", ("pending",))
        """
        self._assert_connected()
        cursor = await self._conn.execute(sql, params)  # type: ignore[union-attr]
        row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def execute_many(
        self,
        sql: str,
        params_seq: list[tuple[Any, ...]],
    ) -> None:
        """
        Execute a write statement for each item in params_seq in a single
        transaction. Useful for bulk inserts.

        Usage:
            await db.execute_many(
                "INSERT INTO custom_tracks (title, artist) VALUES (?, ?)",
                [("Track 1", "Artist A"), ("Track 2", "Artist B")],
            )
        """
        self._assert_connected()
        await self._conn.executemany(sql, params_seq)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _assert_connected(self) -> None:
        if self._conn is None:
            raise RuntimeError(
                "AsyncDB is not connected. "
                "Call await db.connect() before issuing queries."
            )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

# Module-level singleton — one connection for the lifetime of the process.
# Initialised in the FastAPI lifespan handler in main.py.
_db_instance: AsyncDB | None = None


def init_db(path: str) -> AsyncDB:
    """
    Create and store the module-level AsyncDB instance.
    Called once from the FastAPI lifespan handler in main.py:

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            db = init_db(settings.db_path)
            await db.connect()
            await db.create_tables()
            yield
            await db.close()
    """
    global _db_instance
    _db_instance = AsyncDB(path)
    return _db_instance


async def get_db() -> AsyncGenerator[AsyncDB, None]:
    """
    FastAPI dependency. Yields the shared AsyncDB instance.

    Usage in any route:
        async def my_route(db: Annotated[AsyncDB, Depends(get_db)]) -> ...:
            row = await db.fetchone("SELECT ...")

    In tests, conftest.py overrides this via app.dependency_overrides[get_db].
    Never open a new connection inside a route — always use this dependency.
    """
    if _db_instance is None:
        raise RuntimeError(
            "Database has not been initialised. "
            "Ensure init_db() is called in the FastAPI lifespan handler."
        )
    yield _db_instance
