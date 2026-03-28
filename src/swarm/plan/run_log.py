"""Run log model and I/O for plan execution tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StepOutcome:
    """Result of executing a single plan step."""

    step_id: str
    status: str  # "completed", "failed", "skipped"
    started_at: str
    finished_at: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepOutcome:
        return cls(
            step_id=d["step_id"],
            status=d["status"],
            started_at=d["started_at"],
            finished_at=d["finished_at"],
            message=d.get("message", ""),
        )


@dataclass
class RunLog:
    """Execution log for a plan run."""

    plan_path: str
    plan_version: int
    started_at: str
    finished_at: str = ""
    status: str = "running"  # "running", "completed", "paused", "failed"
    steps: list[StepOutcome] = field(default_factory=list)

    @property
    def completed_step_ids(self) -> set[str]:
        """Return IDs of steps that completed successfully."""
        return {s.step_id for s in self.steps if s.status == "completed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_path": self.plan_path,
            "plan_version": self.plan_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunLog:
        return cls(
            plan_path=d["plan_path"],
            plan_version=d["plan_version"],
            started_at=d["started_at"],
            finished_at=d.get("finished_at", ""),
            status=d.get("status", "running"),
            steps=[StepOutcome.from_dict(s) for s in d.get("steps", [])],
        )


def write_run_log(log: RunLog, path: Path) -> None:
    """Write the run log to a JSON file."""
    path.write_text(json.dumps(log.to_dict(), indent=2) + "\n")


def load_run_log(path: Path) -> RunLog:
    """Load a run log from a JSON file."""
    data = json.loads(path.read_text())
    return RunLog.from_dict(data)


def append_step_outcome(log_path: Path, outcome: StepOutcome) -> RunLog:
    """Load, append an outcome, and re-write the log."""
    log = load_run_log(log_path)
    log.steps.append(outcome)
    write_run_log(log, log_path)
    return log
