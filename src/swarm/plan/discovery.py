"""Discover plan directories by walking up the filesystem."""

from __future__ import annotations

from pathlib import Path


def find_plans_dir(start: Path | None = None) -> Path | None:
    """Walk up from *start* looking for a directory containing plans.

    Returns the first directory that either contains ``plan_v*.json``
    files or has a ``.swarm/`` project marker.  Returns ``None`` if no
    such directory is found.
    """
    current = (start or Path.cwd()).resolve()
    while True:
        if list(current.glob("plan_v*.json")):
            return current
        if (current / ".swarm").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
