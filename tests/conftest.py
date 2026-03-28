"""Shared pytest fixtures for the Swarm test suite."""

from __future__ import annotations

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
