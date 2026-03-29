"""SQLite database initialization for the agent registry."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path


def init_registry_db(path: Path) -> sqlite3.Connection:
    """Create (or open) the registry database and ensure the schema exists.

    Args:
        path: Path to the SQLite database file.

    Returns:
        An open ``sqlite3.Connection`` with WAL mode and foreign keys enabled.
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
    ]:
        with contextlib.suppress(sqlite3.OperationalError):
            col_type = "INTEGER" if default == "0" else "TEXT"
            conn.execute(
                f"ALTER TABLE agents ADD COLUMN {col} {col_type} NOT NULL DEFAULT {default}"
            )
    conn.commit()
    return conn
