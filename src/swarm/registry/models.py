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
    description: str = ""
    tags: tuple[str, ...] = ()
    source: str = "forge"
    parent_id: str | None = None
    created_at: str = ""
    usage_count: int = 0
    failure_count: int = 0
    last_used: str = ""
    notes: str = ""

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
            "description": self.description,
            "tags": list(self.tags),
            "source": self.source,
            "created_at": self.created_at,
            "usage_count": self.usage_count,
            "failure_count": self.failure_count,
            "last_used": self.last_used,
            "notes": self.notes,
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
            description=d.get("description", ""),
            tags=tuple(d.get("tags", [])),
            source=d.get("source", "forge"),
            created_at=d.get("created_at", ""),
            usage_count=d.get("usage_count", 0),
            failure_count=d.get("failure_count", 0),
            last_used=d.get("last_used", ""),
            notes=d.get("notes", ""),
        )
