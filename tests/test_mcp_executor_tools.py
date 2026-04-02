"""Tests for swarm.mcp.executor_tools: plan_run, plan_run_status, plan_run_resume, plan_run_cancel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.mcp.executor_tools import (
    plan_run,
    plan_run_cancel,
    plan_run_resume,
    plan_run_status,
)
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, StepOutcome, load_run_log, write_run_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plan(tmp_path: Path, plan_data: dict[str, Any] | None = None) -> Path:
    if plan_data is None:
        plan_data = {
            "version": 1,
            "goal": "test goal",
            "steps": [
                {"id": "s1", "type": "task", "prompt": "do stuff", "agent_type": "worker"},
                {
                    "id": "s2",
                    "type": "task",
                    "prompt": "next",
                    "agent_type": "worker",
                    "depends_on": ["s1"],
                },
            ],
        }
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


def _write_run_log(
    tmp_path: Path,
    plan_path: str,
    status: str = "running",
    steps: list[StepOutcome] | None = None,
    checkpoint_step_id: str = "",
) -> Path:
    log_path = tmp_path / "run_log.json"
    log = RunLog(
        plan_path=plan_path,
        plan_version=1,
        started_at="2025-01-01T00:00:00+00:00",
        status=status,
        steps=steps or [],
        checkpoint_step_id=checkpoint_step_id,
    )
    write_run_log(log, log_path)
    return log_path


# ---------------------------------------------------------------------------
# plan_run
# ---------------------------------------------------------------------------


class TestPlanRun:
    def test_invalid_path_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_run(str(tmp_path / "nonexistent.json")))
        assert "error" in result
        assert "not found" in result["error"]

    def test_dry_run(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        result = json.loads(plan_run(str(plan_path), dry_run="true"))
        assert result["dry_run"] is True
        assert result["total_steps"] == 2
        assert result["waves"] >= 1
        assert len(result["steps"]) == 2

    def test_dry_run_shows_waves(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "test",
            "steps": [
                {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "s2", "type": "task", "prompt": "p", "agent_type": "w"},
                {
                    "id": "s3",
                    "type": "task",
                    "prompt": "p",
                    "agent_type": "w",
                    "depends_on": ["s1", "s2"],
                },
            ],
        }
        plan_path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_run(str(plan_path), dry_run="true"))
        assert result["waves"] == 2

    def test_invalid_plan_json_returns_error(self, tmp_path: Path) -> None:
        path = tmp_path / "plan_v1.json"
        path.write_text("not valid json", encoding="utf-8")
        result = json.loads(plan_run(str(path)))
        assert "error" in result

    @patch("swarm.mcp.executor_tools.execute_plan")
    @patch("swarm.mcp.executor_tools.init_run_state")
    @patch("swarm.mcp.executor_tools.load_plan")
    def test_plan_run_calls_executor(
        self,
        mock_load: MagicMock,
        mock_init: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        plan_path = _write_plan(tmp_path)
        plan = Plan(
            version=1,
            goal="test",
            steps=[PlanStep(id="s1", type="task", prompt="p", agent_type="w")],
        )
        mock_load.return_value = plan
        mock_init.return_value = MagicMock()
        mock_execute.return_value = {
            "status": "completed",
            "steps_executed": 1,
            "steps_remaining": 0,
            "completed_step_ids": ["s1"],
            "failed_step_ids": [],
            "skipped_step_ids": [],
            "run_log_path": str(tmp_path / "run_log.json"),
            "checkpoint_message": None,
            "errors": [],
        }

        result = json.loads(plan_run(str(plan_path)))

        assert result["status"] == "completed"
        mock_execute.assert_called_once()


# ---------------------------------------------------------------------------
# plan_run_status
# ---------------------------------------------------------------------------


class TestPlanRunStatus:
    def test_missing_log_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_run_status(str(tmp_path / "missing.json")))
        assert "error" in result
        assert "not found" in result["error"]

    def test_returns_progress(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="running",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="t0",
                    finished_at="t1",
                ),
            ],
        )
        result = json.loads(plan_run_status(str(log_path)))
        assert result["status"] == "running"
        assert result["progress"]["completed"] == 1
        assert result["progress"]["total"] == 2
        assert result["last_completed_step"] == "s1"

    def test_shows_next_ready_steps(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="running",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="t0",
                    finished_at="t1",
                ),
            ],
        )
        result = json.loads(plan_run_status(str(log_path)))
        assert "s2" in result["next_ready_steps"]

    def test_checkpoint_message(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="paused",
            checkpoint_step_id="cp1",
        )
        result = json.loads(plan_run_status(str(log_path)))
        assert result["checkpoint_message"] is not None
        assert "cp1" in result["checkpoint_message"]

    def test_no_checkpoint_message(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="running",
        )
        result = json.loads(plan_run_status(str(log_path)))
        assert result["checkpoint_message"] is None

    def test_failed_and_skipped_counts(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="failed",
            steps=[
                StepOutcome(step_id="s1", status="failed", started_at="t0", finished_at="t1"),
                StepOutcome(step_id="s2", status="skipped", started_at="t0", finished_at="t1"),
            ],
        )
        result = json.loads(plan_run_status(str(log_path)))
        assert result["progress"]["failed"] == 1
        assert result["progress"]["skipped"] == 1


# ---------------------------------------------------------------------------
# plan_run_resume
# ---------------------------------------------------------------------------


class TestPlanRunResume:
    def test_missing_run_log_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_run_resume(str(tmp_path / "missing.json")))
        assert "error" in result

    def test_already_completed_returns_completed(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="completed",
            steps=[
                StepOutcome(step_id="s1", status="completed", started_at="t0", finished_at="t1"),
                StepOutcome(step_id="s2", status="completed", started_at="t0", finished_at="t1"),
            ],
        )
        result = json.loads(plan_run_resume(str(log_path)))
        assert result["status"] == "completed"
        assert result["steps_executed"] == 2

    def test_resume_after_checkpoint(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "test",
            "steps": [
                {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "cp", "type": "checkpoint", "prompt": "review", "depends_on": ["s1"]},
                {"id": "s2", "type": "task", "prompt": "p", "agent_type": "w", "depends_on": ["cp"]},
            ],
        }
        plan_path = _write_plan(tmp_path, plan_data)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="paused",
            checkpoint_step_id="cp",
            steps=[
                StepOutcome(step_id="s1", status="completed", started_at="t0", finished_at="t1"),
            ],
        )

        with patch("swarm.mcp.executor_tools.execute_plan") as mock_execute:
            mock_execute.return_value = {
                "status": "completed",
                "steps_executed": 1,
                "steps_remaining": 0,
                "completed_step_ids": ["s1", "cp", "s2"],
                "failed_step_ids": [],
                "skipped_step_ids": [],
                "run_log_path": str(log_path),
                "checkpoint_message": None,
                "errors": [],
            }

            result = json.loads(plan_run_resume(str(log_path)))

            assert result["status"] == "completed"
            mock_execute.assert_called_once()

    def test_missing_plan_path_returns_error(self, tmp_path: Path) -> None:
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(tmp_path / "nonexistent_plan.json"),
            status="paused",
        )
        result = json.loads(plan_run_resume(str(log_path)))
        assert "error" in result

    def test_no_plan_path_in_log_or_arg_returns_error(self, tmp_path: Path) -> None:
        log_path = _write_run_log(
            tmp_path,
            plan_path="",
            status="paused",
        )
        result = json.loads(plan_run_resume(str(log_path)))
        assert "error" in result


# ---------------------------------------------------------------------------
# plan_run_cancel
# ---------------------------------------------------------------------------


class TestPlanRunCancel:
    def test_missing_run_log_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_run_cancel(str(tmp_path / "missing.json")))
        assert "error" in result

    def test_cancels_run(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="running",
        )

        result = json.loads(plan_run_cancel(str(log_path)))

        assert result["ok"] is True
        assert result["status"] == "cancelled"

        # Verify the run log was updated
        loaded = load_run_log(log_path)
        assert loaded.status == "cancelled"

    def test_cancel_returns_killed_pids(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path)
        log_path = _write_run_log(
            tmp_path,
            plan_path=str(plan_path),
            status="running",
        )
        result = json.loads(plan_run_cancel(str(log_path)))
        assert "killed_pids" in result
        assert isinstance(result["killed_pids"], list)
