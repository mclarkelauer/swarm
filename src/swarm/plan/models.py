"""Data models for the plan system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FanOutBranch:
    """A single branch in a fan-out step."""

    agent_type: str
    prompt: str
    output_artifact: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"agent_type": self.agent_type, "prompt": self.prompt}
        if self.output_artifact:
            d["output_artifact"] = self.output_artifact
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FanOutBranch:
        return cls(
            agent_type=d["agent_type"],
            prompt=d.get("prompt", ""),
            output_artifact=d.get("output_artifact", ""),
        )


@dataclass(frozen=True)
class FanOutConfig:
    """Configuration for a fan-out step."""

    branches: tuple[FanOutBranch, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"branches": [b.to_dict() for b in self.branches]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FanOutConfig:
        return cls(branches=tuple(FanOutBranch.from_dict(b) for b in d.get("branches", [])))


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
    fan_out_config: FanOutConfig | None = None
    output_artifact: str = ""
    required_inputs: tuple[str, ...] = ()
    on_failure: str = "stop"
    spawn_mode: str = "foreground"
    condition: str = ""
    required_tools: tuple[str, ...] = ()
    critic_agent: str = ""
    max_critic_iterations: int = 3

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
        if self.fan_out_config is not None:
            d["fan_out_config"] = self.fan_out_config.to_dict()
        if self.output_artifact:
            d["output_artifact"] = self.output_artifact
        if self.required_inputs:
            d["required_inputs"] = list(self.required_inputs)
        if self.on_failure != "stop":
            d["on_failure"] = self.on_failure
        if self.spawn_mode != "foreground":
            d["spawn_mode"] = self.spawn_mode
        if self.condition:
            d["condition"] = self.condition
        if self.required_tools:
            d["required_tools"] = list(self.required_tools)
        if self.critic_agent:
            d["critic_agent"] = self.critic_agent
        if self.max_critic_iterations != 3:
            d["max_critic_iterations"] = self.max_critic_iterations
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanStep:
        loop_config = None
        if "loop_config" in d:
            loop_config = LoopConfig.from_dict(d["loop_config"])
        checkpoint_config = None
        if "checkpoint_config" in d:
            checkpoint_config = CheckpointConfig.from_dict(d["checkpoint_config"])
        fan_out_config = None
        if "fan_out_config" in d:
            fan_out_config = FanOutConfig.from_dict(d["fan_out_config"])
        return cls(
            id=d["id"],
            type=d["type"],
            prompt=d.get("prompt", ""),
            agent_type=d.get("agent_type", ""),
            depends_on=tuple(d.get("depends_on", [])),
            loop_config=loop_config,
            checkpoint_config=checkpoint_config,
            fan_out_config=fan_out_config,
            output_artifact=d.get("output_artifact", ""),
            required_inputs=tuple(d.get("required_inputs", [])),
            on_failure=d.get("on_failure", "stop"),
            spawn_mode=d.get("spawn_mode", "foreground"),
            condition=d.get("condition", ""),
            required_tools=tuple(d.get("required_tools", [])),
            critic_agent=d.get("critic_agent", ""),
            max_critic_iterations=d.get("max_critic_iterations", 3),
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
