"""Local directory source for agent definitions."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.errors import RegistryError
from swarm.registry.models import AgentDefinition
from swarm.registry.sources import SourcePlugin


class LocalDirectorySource(SourcePlugin):
    """Scans a local directory for ``.json`` agent definition files.

    Each JSON file must deserialize into a valid :class:`AgentDefinition`.
    Malformed files are silently skipped during search but raise on install.

    Args:
        directory: Path to the directory containing JSON definition files.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def name(self) -> str:
        return "local"

    def _load_all(self) -> list[AgentDefinition]:
        if not self._directory.is_dir():
            return []
        results: list[AgentDefinition] = []
        for path in sorted(self._directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(AgentDefinition.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return results

    def search(self, query: str) -> list[AgentDefinition]:
        """Filter definitions by name substring."""
        return [d for d in self._load_all() if query.lower() in d.name.lower()]

    def install(self, name: str) -> AgentDefinition:
        """Load a definition by exact filename (without extension)."""
        path = self._directory / f"{name}.json"
        if not path.exists():
            raise RegistryError(f"Definition file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return AgentDefinition.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RegistryError(f"Invalid definition in {path}: {exc}") from exc
