"""SQLite database initialization for the agent registry."""

from __future__ import annotations

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
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            parent_id   TEXT,
            system_prompt TEXT NOT NULL DEFAULT '',
            tools       TEXT NOT NULL DEFAULT '[]',
            permissions TEXT NOT NULL DEFAULT '[]',
            working_dir TEXT NOT NULL DEFAULT '',
            source      TEXT NOT NULL DEFAULT 'forge',
            created_at  TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (parent_id) REFERENCES agents(id)
        )
        """
    )
    conn.commit()
    return conn
