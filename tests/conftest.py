"""Shared pytest fixtures for the Swarm test suite."""

from __future__ import annotations

import gc
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.config import SwarmConfig
from swarm.dirs import ensure_base_dir


@pytest.fixture()
def tmp_throng_home(tmp_path: Path) -> Path:
    """Create an isolated Swarm base directory tree inside ``tmp_path``.

    Returns:
        Path to the temporary Swarm home directory.
    """
    throng_home = tmp_path / ".swarm"
    ensure_base_dir(throng_home)
    return throng_home


@pytest.fixture()
def mock_config(tmp_throng_home: Path) -> SwarmConfig:
    """Return a ``SwarmConfig`` whose ``base_dir`` points at the temp directory."""
    return SwarmConfig(base_dir=tmp_throng_home)


def _live_sqlite_connections() -> int:
    """Return the count of currently live ``sqlite3.Connection`` objects."""
    return sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))


@pytest.fixture()
def assert_no_db_leak() -> Iterator[None]:
    """Opt-in fixture that asserts no new live ``sqlite3.Connection`` after a test.

    Use by adding ``assert_no_db_leak`` to a test signature.  Skipped when
    ``SWARM_SKIP_LEAK_CHECK=1`` is set (escape hatch for CI debugging).

    The check runs ``gc.collect()`` before snapshotting so finalizable
    objects are accounted for.
    """
    if os.environ.get("SWARM_SKIP_LEAK_CHECK") == "1":
        # Honour the CI escape hatch before doing anything else so a
        # ``return`` inside ``finally`` doesn't silence test exceptions
        # (ruff B012).
        yield
        return

    gc.collect()
    before = _live_sqlite_connections()
    try:
        yield
    finally:
        gc.collect()
        after = _live_sqlite_connections()
        leaked = after - before
        assert leaked <= 0, (
            f"Test leaked {leaked} sqlite3.Connection object(s); "
            f"snapshot grew from {before} to {after}"
        )
