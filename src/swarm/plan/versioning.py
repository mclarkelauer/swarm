"""Plan versioning utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path

from swarm.plan.models import Plan

_VERSION_RE = re.compile(r"^plan_v(\d+)\.json$")


def list_versions(instance_dir: Path) -> list[int]:
    """Return sorted list of plan version numbers in the instance directory."""
    if not instance_dir.is_dir():
        return []
    versions: list[int] = []
    for path in instance_dir.iterdir():
        m = _VERSION_RE.match(path.name)
        if m:
            versions.append(int(m.group(1)))
    return sorted(versions)


def next_version(instance_dir: Path) -> int:
    """Return the next available version number."""
    versions = list_versions(instance_dir)
    return versions[-1] + 1 if versions else 1


def load_version(instance_dir: Path, version: int) -> Plan:
    """Load a specific plan version.

    Args:
        instance_dir: Swarm instance directory.
        version: Version number to load.

    Returns:
        The ``Plan`` at the given version.

    Raises:
        FileNotFoundError: If the version file does not exist.
    """
    path = instance_dir / f"plan_v{version}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Plan.from_dict(data)
