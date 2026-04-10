"""SQLite database initialization for the agent registry."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path


def init_registry_db(path: Path) -> tuple[sqlite3.Connection, bool]:
    """Create (or open) the registry database and ensure the schema exists.

    Args:
        path: Path to the SQLite database file.

    Returns:
        A tuple of (connection, fts_available) where *fts_available* is
        ``True`` when the FTS5 extension is compiled into the SQLite build
        and the full-text index was created successfully.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            parent_id     TEXT,
            system_prompt TEXT NOT NULL DEFAULT '',
            tools         TEXT NOT NULL DEFAULT '[]',
            permissions   TEXT NOT NULL DEFAULT '[]',
            working_dir   TEXT NOT NULL DEFAULT '',
            source        TEXT NOT NULL DEFAULT 'forge',
            created_at    TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            tags          TEXT NOT NULL DEFAULT '[]',
            usage_count   INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_used     TEXT NOT NULL DEFAULT '',
            notes         TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (parent_id) REFERENCES agents(id)
        )
        """
    )
    for col, default in [
        ("description", "''"),
        ("tags", "'[]'"),
        ("usage_count", "0"),
        ("failure_count", "0"),
        ("last_used", "''"),
        ("notes", "''"),
        ("status", "'active'"),
        ("version", "1"),
    ]:
        with contextlib.suppress(sqlite3.OperationalError):
            col_type = "INTEGER" if default == "0" else "TEXT"
            conn.execute(
                f"ALTER TABLE agents ADD COLUMN {col} {col_type} NOT NULL DEFAULT {default}"
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_metrics (
            agent_name    TEXT PRIMARY KEY,
            total_runs    INTEGER NOT NULL DEFAULT 0,
            total_successes INTEGER NOT NULL DEFAULT 0,
            total_failures  INTEGER NOT NULL DEFAULT 0,
            total_tokens    INTEGER NOT NULL DEFAULT 0,
            total_cost_usd  REAL NOT NULL DEFAULT 0.0,
            avg_duration_seconds REAL NOT NULL DEFAULT 0.0,
            last_run_at   TEXT NOT NULL DEFAULT '',
            updated_at    TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()

    fts_available = _init_fts(conn)
    return conn, fts_available


def _init_fts(conn: sqlite3.Connection) -> bool:
    """Attempt to create the FTS5 full-text index on the agents table.

    Uses **external content** mode so the FTS5 virtual table reads from
    the ``agents`` table on demand without duplicating data.  Sync
    triggers keep the index consistent on every INSERT / UPDATE / DELETE.

    Args:
        conn: An open SQLite connection with the ``agents`` table already
            created.

    Returns:
        ``True`` if FTS5 is available and the index was set up
        successfully.  ``False`` when the FTS5 extension is not compiled
        into the SQLite build — the caller should fall back to LIKE
        search.
    """
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS agents_fts USING fts5(
                name,
                description,
                system_prompt,
                tags,
                content='agents',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS agents_fts_insert
            AFTER INSERT ON agents BEGIN
                INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
                VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_update_delete
            BEFORE UPDATE ON agents BEGIN
                INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
                VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_update_insert
            AFTER UPDATE ON agents BEGIN
                INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
                VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_delete
            AFTER DELETE ON agents BEGIN
                INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
                VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
            END;

            -- Rebuild to ensure consistency with any rows inserted before triggers existed
            INSERT INTO agents_fts(agents_fts) VALUES ('rebuild');
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        # FTS5 extension not available — fall back to LIKE search
        return False
