"""Run log model and I/O for plan execution tracking."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swarm.errors import RunLogCorruptError


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
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""

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
        if self.tokens_used > 0:
            d["tokens_used"] = self.tokens_used
        if self.cost_usd > 0.0:
            d["cost_usd"] = self.cost_usd
        if self.model:
            d["model"] = self.model
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
            tokens_used=d.get("tokens_used", 0),
            cost_usd=d.get("cost_usd", 0.0),
            model=d.get("model", ""),
        )


@dataclass(frozen=True)
class BackgroundStepRecord:
    """Persistent record of an in-flight background subprocess.

    Recorded when a background or fan-out step is launched and removed when
    it completes.  On crash recovery the executor walks the surviving
    records, probes each PID with ``os.kill(pid, 0)``, and either reattaches
    polling or marks the step as failed (depending on ``on_failure``).

    For fan-out branches the ``step_id`` uses the canonical ``base::index``
    form and ``branch_index`` records the branch ordinal.
    """

    step_id: str
    pid: int
    started_at: str
    branch_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step_id": self.step_id,
            "pid": self.pid,
            "started_at": self.started_at,
        }
        if self.branch_index is not None:
            d["branch_index"] = self.branch_index
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BackgroundStepRecord:
        return cls(
            step_id=d["step_id"],
            pid=d["pid"],
            started_at=d["started_at"],
            branch_index=d.get("branch_index"),
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
    background_steps: list[BackgroundStepRecord] = field(default_factory=list)

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
        if self.background_steps:
            d["background_steps"] = [b.to_dict() for b in self.background_steps]
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
            background_steps=[
                BackgroundStepRecord.from_dict(b)
                for b in d.get("background_steps", [])
            ],
        )


def _backup_path(path: Path) -> Path:
    """Return the rolling ``.prev`` backup path for *path*."""
    return path.with_suffix(path.suffix + ".prev")


def write_run_log(log: RunLog, path: Path) -> None:
    """Write the run log to a JSON file atomically.

    Writes to a temporary file first, then performs an atomic
    ``os.replace()`` to avoid partial writes on crash.  Before the
    replace, the existing file (if any) is copied to a rolling
    ``.prev`` backup so a subsequent corruption of the primary file
    can fall back to the previous good snapshot.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(log.to_dict(), indent=2) + "\n")
    if path.exists():
        backup = _backup_path(path)
        # Best-effort backup; don't block the primary write on backup error.
        with contextlib.suppress(OSError):
            shutil.copy2(path, backup)
    os.replace(tmp, path)


def load_run_log(path: Path) -> RunLog:
    """Load a run log from a JSON file.

    Raises ``json.JSONDecodeError`` or ``KeyError`` on a malformed file.
    Use :func:`load_run_log_resilient` for resume-time loads that should
    fall back to backups or reconstruction.
    """
    data = json.loads(path.read_text())
    return RunLog.from_dict(data)


def append_step_outcome(log_path: Path, outcome: StepOutcome) -> RunLog:
    """Load, append an outcome, and re-write the log."""
    log = load_run_log(log_path)
    log.steps.append(outcome)
    write_run_log(log, log_path)
    return log


# ---------------------------------------------------------------------------
# Resilient loading / reconstruction
# ---------------------------------------------------------------------------


def reconstruct_run_log_from_events(
    events_path: Path,
    plan_path: str = "",
    plan_version: int = 0,
) -> RunLog:
    """Rebuild a :class:`RunLog` from a NDJSON event log.

    Walks every ``step_completed``, ``step_failed``, and ``step_skipped``
    event in *events_path* and constructs corresponding
    :class:`StepOutcome` rows.  ``plan_path`` and ``plan_version`` are
    populated from a ``run_started`` event's ``data`` payload when present
    or from the explicit args.

    Raises:
        RunLogCorruptError: If the events log is missing or contains no
            usable events.
    """
    if not events_path.exists():
        raise RunLogCorruptError(
            f"Cannot reconstruct: events log not found at {events_path}"
        )

    events: list[dict[str, Any]] = []
    with events_path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue

    if not events:
        raise RunLogCorruptError(
            f"Cannot reconstruct: events log {events_path} contained no "
            "valid events"
        )

    started_at = ""
    finished_at = ""
    status = "running"
    resolved_plan_path = plan_path
    resolved_plan_version = plan_version
    checkpoint_step_id = ""

    for ev in events:
        et = ev.get("event_type", "")
        ts = ev.get("timestamp", "")
        if et == "run_started" and not started_at:
            started_at = ts
            data = ev.get("data") or {}
            if not resolved_plan_path:
                resolved_plan_path = str(data.get("plan_path", ""))
            if not resolved_plan_version:
                resolved_plan_version = int(data.get("plan_version", 0) or 0)
        elif et == "run_completed":
            finished_at = ts
            msg = ev.get("message", "")
            if msg in {"completed", "failed", "paused", "cancelled"}:
                status = msg
        elif et == "checkpoint_reached":
            checkpoint_step_id = ev.get("step_id", "") or checkpoint_step_id

    if not started_at:
        started_at = events[0].get("timestamp", "")

    # Reconstruct outcomes — keep the latest record per step for steps
    # that may have been retried.
    outcomes: list[StepOutcome] = []
    seen: set[str] = set()
    for ev in events:
        et = ev.get("event_type", "")
        if et not in {"step_completed", "step_failed", "step_skipped"}:
            continue
        step_id = ev.get("step_id", "")
        if not step_id:
            continue
        if step_id in seen:
            outcomes = [o for o in outcomes if o.step_id != step_id]
        seen.add(step_id)
        status_map = {
            "step_completed": "completed",
            "step_failed": "failed",
            "step_skipped": "skipped",
        }
        outcome_status = status_map[et]
        ts = ev.get("timestamp", "")
        outcomes.append(
            StepOutcome(
                step_id=step_id,
                status=outcome_status,
                started_at=ts,
                finished_at=ts,
                message=ev.get("message", ""),
            )
        )

    return RunLog(
        plan_path=resolved_plan_path,
        plan_version=resolved_plan_version,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        steps=outcomes,
        checkpoint_step_id=checkpoint_step_id,
    )


def load_run_log_resilient(
    path: Path,
    events_path: Path | None = None,
) -> RunLog:
    """Load a run log, recovering from corruption when possible.

    Recovery strategy (in order):

    1. Parse *path* directly.
    2. Fall back to the rolling ``<path>.prev`` backup.
    3. Reconstruct from *events_path* (defaults to
       ``<path>.parent / "events.ndjson"``) using
       :func:`reconstruct_run_log_from_events`.

    Raises:
        RunLogCorruptError: When every recovery path fails.  This is
            intentionally loud — the caller should NOT silently treat the
            run as fresh, which would re-execute previously completed
            steps.
    """
    if path.exists():
        try:
            return load_run_log(path)
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    backup = _backup_path(path)
    if backup.exists():
        try:
            return load_run_log(backup)
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    ev_path = events_path if events_path is not None else (
        path.parent / "events.ndjson"
    )
    if ev_path.exists():
        return reconstruct_run_log_from_events(ev_path)

    raise RunLogCorruptError(
        f"Run log at {path} is corrupt and no backup or events.ndjson "
        "is available to reconstruct it. Refusing to silently treat "
        "this as a fresh run, which would re-execute completed steps."
    )
