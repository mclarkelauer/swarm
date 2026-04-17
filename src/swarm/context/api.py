"""Run-scoped shared context (blackboard) for inter-agent data sharing."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from swarm._db_pool import ThreadLocalConnectionPool, apply_default_pragmas


def init_context_schema(conn: sqlite3.Connection) -> None:
    """Install the shared-context schema on a connection. Idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS context (
            run_id    TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT NOT NULL DEFAULT '',
            set_by    TEXT NOT NULL DEFAULT '',
            set_at    TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (run_id, key)
        )
        """
    )
    conn.commit()


def init_context_db(path: Path) -> sqlite3.Connection:
    """Create or open the shared context database (single-connection helper)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    apply_default_pragmas(conn)
    init_context_schema(conn)
    return conn


class SharedContextAPI:
    """Key-value store scoped per plan run.

    Enables agents to share structured data within a run without
    file-based artifacts.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._pool: ThreadLocalConnectionPool = ThreadLocalConnectionPool(
            db_path, initializer=init_context_schema,
        )
        # Eagerly create the schema on the owning thread.
        self._pool.get()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the SQLite connection bound to the calling thread."""
        return self._pool.get()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Backwards-compatible alias for :meth:`_get_conn`."""
        return self._pool.get()

    def set(
        self,
        run_id: str,
        key: str,
        value: str,
        set_by: str = "",
    ) -> dict[str, str]:
        """Set a key-value pair in the shared context.

        Args:
            run_id: Plan run identifier.
            key: Context key.
            value: Context value (typically JSON-encoded).
            set_by: Agent/step that set this value.

        Returns:
            Dict with the stored entry.
        """
        now = datetime.now(tz=UTC).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO context (run_id, key, value, set_by, set_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, key, value, set_by, now),
        )
        self._conn.commit()
        return {"run_id": run_id, "key": key, "value": value, "set_by": set_by, "set_at": now}

    def get(self, run_id: str, key: str) -> str | None:
        """Get a value from the shared context.

        Args:
            run_id: Plan run identifier.
            key: Context key.

        Returns:
            The value string, or None if not found.
        """
        cur = self._conn.execute(
            "SELECT value FROM context WHERE run_id = ? AND key = ?",
            (run_id, key),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def get_all(self, run_id: str) -> dict[str, str]:
        """Get all key-value pairs for a run.

        Args:
            run_id: Plan run identifier.

        Returns:
            Dict of key -> value.
        """
        cur = self._conn.execute(
            "SELECT key, value FROM context WHERE run_id = ? ORDER BY key",
            (run_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    def delete(self, run_id: str, key: str) -> bool:
        """Delete a key from the shared context.

        Returns:
            True if the key existed and was deleted.
        """
        cur = self._conn.execute(
            "DELETE FROM context WHERE run_id = ? AND key = ?",
            (run_id, key),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self, run_id: str) -> int:
        """Clear all context for a run.

        Returns:
            Number of entries deleted.
        """
        cur = self._conn.execute(
            "DELETE FROM context WHERE run_id = ?",
            (run_id,),
        )
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        """Return the number of stored context entries across all runs.

        Returns:
            Number of rows in the ``context`` table.
        """
        cur = self._get_conn().execute("SELECT COUNT(*) FROM context")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close every thread-local SQLite connection."""
        self._pool.close_all()

    def __enter__(self) -> SharedContextAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
