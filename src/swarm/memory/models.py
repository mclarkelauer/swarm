"""Data models for the agent memory system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry for an agent.

    Memories are keyed by agent_name (not agent_id) because agent
    definitions are immutable -- clones share the same name and should
    share the same memory.
    """

    id: str
    agent_name: str
    content: str
    memory_type: str = "semantic"
    context: str = ""
    created_at: str = ""
    relevance_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Sparse serialization -- omit fields at their default value."""
        d: dict[str, Any] = {
            "id": self.id,
            "agent_name": self.agent_name,
            "content": self.content,
        }
        if self.memory_type != "semantic":
            d["memory_type"] = self.memory_type
        if self.context:
            d["context"] = self.context
        if self.created_at:
            d["created_at"] = self.created_at
        if self.relevance_score != 1.0:
            d["relevance_score"] = self.relevance_score
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryEntry:
        """Deserialize with backward-compatible defaults."""
        return cls(
            id=d["id"],
            agent_name=d["agent_name"],
            content=d["content"],
            memory_type=d.get("memory_type", "semantic"),
            context=d.get("context", ""),
            created_at=d.get("created_at", ""),
            relevance_score=d.get("relevance_score", 1.0),
        )
