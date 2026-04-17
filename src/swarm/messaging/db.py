"""SQLite database initialization for the inter-agent message bus."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path


def _migrate_drop_message_type_check(conn: sqlite3.Connection) -> None:
    """Drop the legacy ``CHECK (message_type IN (...))`` constraint, if present.

    Round 5 added negotiation message types (``proposal``, ``counter``,
    ``accept``, ``reject``) on the validator side but left the original
    schema's three-value CHECK constraint in place, so the new types
    raised :class:`sqlite3.IntegrityError` at insert time.

    SQLite has no ``ALTER TABLE DROP CONSTRAINT``, so we detect the old
    constraint by inspecting ``sqlite_master`` and, if found, recreate
    the table without it inside a single transaction:

      1. Rename the old table to ``messages_old``.
      2. Create the new ``messages`` table without the CHECK clause.
      3. Copy every row over (column lists are identical).
      4. Drop ``messages_old``.

    This function is idempotent — once the constraint is gone the
    schema definition no longer contains ``CHECK (message_type``, so the
    detection path skips the rebuild on subsequent calls.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if row is None:
        return
    create_sql = row[0] or ""
    if "CHECK (message_type" not in create_sql:
        return

    # Discover the live column list so the rebuild preserves any
    # previously-applied ALTER TABLE additions (in_reply_to, read_at).
    cols_info = conn.execute("PRAGMA table_info(messages)").fetchall()
    col_names = [str(row[1]) for row in cols_info]
    col_list = ", ".join(col_names)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("ALTER TABLE messages RENAME TO messages_old")
        conn.execute(
            """
            CREATE TABLE messages (
                id          TEXT PRIMARY KEY,
                from_agent  TEXT NOT NULL,
                to_agent    TEXT NOT NULL,
                step_id     TEXT NOT NULL DEFAULT '',
                run_id      TEXT NOT NULL DEFAULT '',
                content     TEXT NOT NULL DEFAULT '',
                message_type TEXT NOT NULL DEFAULT 'response',
                created_at  TEXT NOT NULL DEFAULT '',
                in_reply_to TEXT NOT NULL DEFAULT '',
                read_at     TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Bring rows across.  Use the column list discovered above so
        # any subset of columns survives — extras default to ''.
        conn.execute(
            f"INSERT INTO messages ({col_list}) "
            f"SELECT {col_list} FROM messages_old"
        )
        conn.execute("DROP TABLE messages_old")
        # Indexes were dropped with the rename — recreate below.
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.commit()


def init_message_schema(conn: sqlite3.Connection) -> None:
    """Install the messaging schema (tables, indexes) on a connection.

    Idempotent — safe to call repeatedly.

    Args:
        conn: An open SQLite connection.  Default Swarm PRAGMAs are
            expected to have already been applied by the caller.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL,
            step_id     TEXT NOT NULL DEFAULT '',
            run_id      TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            message_type TEXT NOT NULL DEFAULT 'response',
            created_at  TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Drop the legacy CHECK constraint, if a pre-Round-5 database is
    # being opened.  Idempotent and only does work on outdated schemas.
    _migrate_drop_message_type_check(conn)

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_run_to_agent
            ON messages(run_id, to_agent);

        CREATE INDEX IF NOT EXISTS idx_messages_run_step
            ON messages(run_id, step_id);
        """
    )
    # Idempotent migrations for new columns.
    for col in ("in_reply_to", "read_at"):
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                f"ALTER TABLE messages ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
            )
    conn.commit()


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
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    init_message_schema(conn)
    return conn
