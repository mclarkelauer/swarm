"""Thread-local SQLite connection pool used by the persistence APIs.

`sqlite3.Connection` objects raise :class:`sqlite3.ProgrammingError` when
shared across threads (the default ``check_same_thread=True`` guard).
The Swarm executor uses a :class:`concurrent.futures.ThreadPoolExecutor`
for parallel foreground execution, which means
``MemoryAPI.recall`` (and other persistence APIs) can be invoked from
arbitrary worker threads.

This module provides :class:`ThreadLocalConnectionPool`, a small helper
that lazily creates one connection per thread per database path and
applies a consistent set of PRAGMAs.  The owning API class is
responsible for storing the pool, calling :meth:`get` on every query,
and calling :meth:`close_all` when the API is closed.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


def apply_default_pragmas(conn: sqlite3.Connection) -> None:
    """Apply the standard Swarm SQLite PRAGMAs to a fresh connection.

    The settings favour multi-threaded reads, modest durability, and
    enough patience for transient writer locks (5 second busy timeout).

    Args:
        conn: A freshly opened :class:`sqlite3.Connection`.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")


class ThreadLocalConnectionPool:
    """Lazy per-thread SQLite connection factory.

    The pool owns a :class:`threading.local` for storing the calling
    thread's connection, plus a global ``set`` of every connection
    handed out.  :meth:`close_all` iterates the latter to ensure every
    underlying file handle is released, regardless of which thread
    created it.

    Thread safety:
        - :meth:`get` is safe to call from any thread.  It only reads
          ``self._local.conn`` (thread-local, no lock needed) and, on
          cache miss, takes ``self._lock`` long enough to register the
          new connection in the global tracking set.
        - :meth:`close_all` takes ``self._lock`` to drain the tracking
          set; subsequent :meth:`get` calls re-create connections.

    Args:
        db_path: Filesystem path to the SQLite database file.
        initializer: Optional callable invoked once per new connection
            (after the default PRAGMAs are applied) to install
            schema, indexes, FTS triggers, etc.  When provided, the
            initializer is invoked under a class-level lock so that the
            schema-creation path runs serially across threads even
            during the first burst of concurrent calls.
    """

    def __init__(
        self,
        db_path: Path,
        initializer: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> None:
        self._db_path = db_path
        self._initializer = initializer
        self._local: threading.local = threading.local()
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._all_conns: set[sqlite3.Connection] = set()
        self._closed = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def get(self) -> sqlite3.Connection:
        """Return the calling thread's connection, creating it on first use.

        Raises:
            sqlite3.ProgrammingError: If the pool has been closed via
                :meth:`close_all`.
        """
        if self._closed:
            raise sqlite3.ProgrammingError(
                "Cannot operate on a closed database pool."
            )
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        new_conn = sqlite3.connect(str(self._db_path))
        apply_default_pragmas(new_conn)

        if self._initializer is not None:
            # Schema creation is idempotent (CREATE ... IF NOT EXISTS) but
            # we still serialize it to avoid concurrent SQLITE_BUSY storms
            # on the first call from multiple threads.
            with self._init_lock:
                self._initializer(new_conn)

        self._local.conn = new_conn
        with self._lock:
            self._all_conns.add(new_conn)
        return new_conn

    def close_all(self) -> None:
        """Close every connection ever handed out by this pool.

        Marks the pool as closed; subsequent :meth:`get` calls raise
        :class:`sqlite3.ProgrammingError` to surface use-after-close
        bugs the way :meth:`sqlite3.Connection.close` would.

        Safe to call multiple times.
        """
        with self._lock:
            conns = list(self._all_conns)
            self._all_conns.clear()
            self._closed = True
        for conn in conns:
            # Already-closed or otherwise broken connection — best
            # effort cleanup, do not raise from close().
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        # Drop this thread's reference too.
        if hasattr(self._local, "conn"):
            with contextlib.suppress(AttributeError):
                delattr(self._local, "conn")

    def open_count(self) -> int:
        """Return the number of currently-tracked connections."""
        with self._lock:
            return len(self._all_conns)
