"""Directory management for Swarm.

Provides helpers for creating the ``~/.swarm`` directory tree.
All paths are ``pathlib.Path`` objects; string paths are never used.
"""

from __future__ import annotations

from pathlib import Path


def ensure_base_dir(base: Path) -> None:
    """Create the Swarm base directory tree if it does not exist.

    Creates the following structure::

        base/
          forge/

    Args:
        base: Root Swarm directory (typically ``~/.swarm``).
    """
    (base / "forge").mkdir(parents=True, exist_ok=True)
