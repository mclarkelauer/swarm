"""Data models for the agent registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    """Immutable definition of an agent type.

    Modifications create clones with provenance tracking via ``parent_id``.
    """

    id: str
    name: str
    system_prompt: str
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    working_dir: str = ""
    source: str = "forge"
    parent_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary suitable for JSON encoding."""
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "system_prompt": self.system_prompt,
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "working_dir": self.working_dir,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentDefinition:
        """Deserialize from a dictionary."""
        return cls(
            id=d["id"],
            name=d["name"],
            parent_id=d.get("parent_id"),
            system_prompt=d.get("system_prompt", ""),
            tools=tuple(d.get("tools", [])),
            permissions=tuple(d.get("permissions", [])),
            working_dir=d.get("working_dir", ""),
            source=d.get("source", "forge"),
            created_at=d.get("created_at", ""),
        )
