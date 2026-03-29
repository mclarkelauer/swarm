"""Project-local source for agent definitions in ``.swarm/agents/``."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from swarm.errors import RegistryError
from swarm.registry.models import AgentDefinition
from swarm.registry.sources import SourcePlugin

_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_URL


class ProjectDirectorySource(SourcePlugin):
    """Scans ``.swarm/agents/*.agent.json`` for project-local agent definitions.

    Each file defines a portable agent (name, system_prompt, tools, permissions).
    IDs are generated deterministically from the file path using UUID5 so the
    same file always maps to the same ID.

    Args:
        project_dir: Project root (containing ``.swarm/``).
    """

    def __init__(self, project_dir: Path) -> None:
        self._agents_dir = project_dir / ".swarm" / "agents"

    @property
    def name(self) -> str:
        return "project"

    def _load_all(self) -> list[AgentDefinition]:
        if not self._agents_dir.is_dir():
            return []
        results: list[AgentDefinition] = []
        for path in sorted(self._agents_dir.glob("*.agent.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                agent_id = str(uuid.uuid5(_NAMESPACE, str(path.resolve())))
                defn = AgentDefinition(
                    id=agent_id,
                    name=data["name"],
                    system_prompt=data["system_prompt"],
                    tools=tuple(data.get("tools", [])),
                    permissions=tuple(data.get("permissions", [])),
                    description=data.get("description", ""),
                    tags=tuple(data.get("tags", [])),
                    source="project",
                )
                results.append(defn)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return results

    def search(self, query: str) -> list[AgentDefinition]:
        """Filter definitions by name or prompt substring."""
        q = query.lower()
        return [
            d for d in self._load_all()
            if q in d.name.lower() or q in d.system_prompt.lower()
        ]

    def install(self, name: str) -> AgentDefinition:
        """Load a definition by exact name."""
        for defn in self._load_all():
            if defn.name == name:
                return defn
        raise RegistryError(f"Agent '{name}' not found in project agents")
