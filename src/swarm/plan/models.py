"""Data models for the plan system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LoopConfig:
    """Configuration for a loop step."""

    condition: str = ""
    max_iterations: int = 100_000

    def to_dict(self) -> dict[str, Any]:
        return {"condition": self.condition, "max_iterations": self.max_iterations}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LoopConfig:
        return cls(
            condition=d.get("condition", ""),
            max_iterations=d.get("max_iterations", 100_000),
        )


@dataclass(frozen=True)
class CheckpointConfig:
    """Configuration for a checkpoint step."""

    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"message": self.message}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CheckpointConfig:
        return cls(message=d.get("message", ""))


@dataclass(frozen=True)
class PlanStep:
    """A single step in the execution plan."""

    id: str
    type: str  # "task", "checkpoint", "loop"
    prompt: str
    agent_type: str = ""
    depends_on: tuple[str, ...] = ()
    loop_config: LoopConfig | None = None
    checkpoint_config: CheckpointConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "prompt": self.prompt,
        }
        if self.agent_type:
            d["agent_type"] = self.agent_type
        if self.depends_on:
            d["depends_on"] = list(self.depends_on)
        if self.loop_config is not None:
            d["loop_config"] = self.loop_config.to_dict()
        if self.checkpoint_config is not None:
            d["checkpoint_config"] = self.checkpoint_config.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanStep:
        loop_config = None
        if "loop_config" in d:
            loop_config = LoopConfig.from_dict(d["loop_config"])
        checkpoint_config = None
        if "checkpoint_config" in d:
            checkpoint_config = CheckpointConfig.from_dict(d["checkpoint_config"])
        return cls(
            id=d["id"],
            type=d["type"],
            prompt=d.get("prompt", ""),
            agent_type=d.get("agent_type", ""),
            depends_on=tuple(d.get("depends_on", [])),
            loop_config=loop_config,
            checkpoint_config=checkpoint_config,
        )


@dataclass
class Plan:
    """An execution plan consisting of ordered steps."""

    version: int
    goal: str
    steps: list[PlanStep]
    variables: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "variables": self.variables,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        return cls(
            version=d["version"],
            goal=d["goal"],
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            variables=d.get("variables", {}),
        )
