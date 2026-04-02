"""Run log model and I/O for plan execution tracking."""

from __future__ import annotations

import json
import os
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
    attempt: int = 0
    exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
        }
        if self.attempt > 0:
            d["attempt"] = self.attempt
        if self.exit_code is not None:
            d["exit_code"] = self.exit_code
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepOutcome:
        return cls(
            step_id=d["step_id"],
            status=d["status"],
            started_at=d["started_at"],
            finished_at=d["finished_at"],
            message=d.get("message", ""),
            attempt=d.get("attempt", 0),
            exit_code=d.get("exit_code"),
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
    executor_version: str = ""
    checkpoint_step_id: str = ""
    replan_count: int = 0

    @property
    def completed_step_ids(self) -> set[str]:
        """Return IDs of steps that completed successfully."""
        return {s.step_id for s in self.steps if s.status == "completed"}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "plan_path": self.plan_path,
            "plan_version": self.plan_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.executor_version:
            d["executor_version"] = self.executor_version
        if self.checkpoint_step_id:
            d["checkpoint_step_id"] = self.checkpoint_step_id
        if self.replan_count > 0:
            d["replan_count"] = self.replan_count
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunLog:
        return cls(
            plan_path=d["plan_path"],
            plan_version=d["plan_version"],
            started_at=d["started_at"],
            finished_at=d.get("finished_at", ""),
            status=d.get("status", "running"),
            steps=[StepOutcome.from_dict(s) for s in d.get("steps", [])],
            executor_version=d.get("executor_version", ""),
            checkpoint_step_id=d.get("checkpoint_step_id", ""),
            replan_count=d.get("replan_count", 0),
        )


def write_run_log(log: RunLog, path: Path) -> None:
    """Write the run log to a JSON file atomically.

    Writes to a temporary file first, then performs an atomic
    ``os.replace()`` to avoid partial writes on crash.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(log.to_dict(), indent=2) + "\n")
    os.replace(tmp, path)


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
