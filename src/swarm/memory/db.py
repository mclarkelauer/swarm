"""SQLite database initialization for the agent memory system."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path


def init_memory_schema(conn: sqlite3.Connection) -> bool:
    """Install the memory schema (tables, indexes, FTS) on a connection.

    Idempotent — safe to call repeatedly.

    Args:
        conn: An open SQLite connection.  Default Swarm PRAGMAs are
            expected to have already been applied by the caller.

    Returns:
        ``True`` when FTS5 is available and the index was set up.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id              TEXT PRIMARY KEY,
            agent_name      TEXT NOT NULL,
            memory_type     TEXT NOT NULL DEFAULT 'semantic',
            content         TEXT NOT NULL,
            context         TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT '',
            relevance_score REAL NOT NULL DEFAULT 1.0
        )
        """
    )

    # Idempotent migrations for future columns
    _migrations: list[tuple[str, str, str]] = [
        # Example future migration:
        # ("access_count", "INTEGER", "0"),
    ]
    for _col, _col_type, _default in _migrations:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                f"ALTER TABLE memory ADD COLUMN {_col} {_col_type} "
                f"NOT NULL DEFAULT {_default}"
            )

    # Indexes
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_agent_name "
            "ON memory(agent_name)"
        )
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_type "
            "ON memory(agent_name, memory_type)"
        )
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_relevance "
            "ON memory(agent_name, relevance_score DESC)"
        )

    conn.commit()

    return _init_memory_fts(conn)


def init_memory_db(path: Path) -> tuple[sqlite3.Connection, bool]:
    """Create (or open) the memory database and ensure schema exists.

    Args:
        path: Path to the SQLite database file.

    Returns:
        Tuple of (connection, fts_available).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    fts_available = init_memory_schema(conn)
    return conn, fts_available


def _init_memory_fts(conn: sqlite3.Connection) -> bool:
    """Attempt to create FTS5 index on memory content. Returns True if available."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                content='memory',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS memory_fts_insert
            AFTER INSERT ON memory BEGIN
                INSERT INTO memory_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_update_delete
            BEFORE UPDATE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_update_insert
            AFTER UPDATE ON memory BEGIN
                INSERT INTO memory_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_delete
            AFTER DELETE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            INSERT INTO memory_fts(memory_fts) VALUES ('rebuild');
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
