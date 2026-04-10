"""Data models for the inter-agent message bus."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

_VALID_MESSAGE_TYPES = ("request", "response", "broadcast")


@dataclass(frozen=True)
class AgentMessage:
    """A single message between agents in a plan run."""

    id: str
    from_agent: str
    to_agent: str
    step_id: str = ""
    run_id: str = ""
    content: str = ""
    message_type: str = "response"
    created_at: str = ""
    in_reply_to: str = ""
    read_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Sparse serialization -- omit fields at their default value."""
        d: dict[str, Any] = {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
        }
        if self.step_id:
            d["step_id"] = self.step_id
        if self.run_id:
            d["run_id"] = self.run_id
        if self.content:
            d["content"] = self.content
        if self.message_type != "response":
            d["message_type"] = self.message_type
        if self.created_at:
            d["created_at"] = self.created_at
        if self.in_reply_to:
            d["in_reply_to"] = self.in_reply_to
        if self.read_at:
            d["read_at"] = self.read_at
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentMessage:
        """Deserialize with backward-compatible defaults."""
        return cls(
            id=d["id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            step_id=d.get("step_id", ""),
            run_id=d.get("run_id", ""),
            content=d.get("content", ""),
            message_type=d.get("message_type", "response"),
            created_at=d.get("created_at", ""),
            in_reply_to=d.get("in_reply_to", ""),
            read_at=d.get("read_at", ""),
        )

    @classmethod
    def create(
        cls,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str = "response",
        step_id: str = "",
        run_id: str = "",
        created_at: str = "",
        in_reply_to: str = "",
        read_at: str = "",
    ) -> AgentMessage:
        """Factory that auto-generates the UUID."""
        return cls(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            step_id=step_id,
            run_id=run_id,
            content=content,
            message_type=message_type,
            created_at=created_at,
            in_reply_to=in_reply_to,
            read_at=read_at,
        )
