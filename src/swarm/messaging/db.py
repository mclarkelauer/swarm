"""SQLite database initialization for the inter-agent message bus."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def init_message_db(path: Path) -> sqlite3.Connection:
    """Create (or open) the message database and ensure schema exists.

    Args:
        path: Path to the SQLite database file.

    Returns:
        An open sqlite3.Connection with WAL mode enabled.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL,
            step_id     TEXT NOT NULL DEFAULT '',
            run_id      TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            message_type TEXT NOT NULL DEFAULT 'response'
                CHECK (message_type IN ('request', 'response', 'broadcast')),
            created_at  TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_messages_run_to_agent
            ON messages(run_id, to_agent);

        CREATE INDEX IF NOT EXISTS idx_messages_run_step
            ON messages(run_id, step_id);
        """
    )
    conn.commit()

    return conn
