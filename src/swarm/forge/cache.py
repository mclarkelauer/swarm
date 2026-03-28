"""Disk cache for agent definitions."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.registry.models import AgentDefinition


def read_cache(cache_dir: Path, name: str) -> AgentDefinition | None:
    """Read a cached agent definition by name.

    Returns ``None`` on cache miss or corrupted data.
    """
    path = cache_dir / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentDefinition.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def write_cache(cache_dir: Path, definition: AgentDefinition) -> None:
    """Write an agent definition to the disk cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{definition.name}.json"
    path.write_text(json.dumps(definition.to_dict(), indent=2), encoding="utf-8")
