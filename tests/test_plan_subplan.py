"""Tests for subplan step execution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.executor import (
    RunState,
    handle_subplan,
)
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, write_run_log


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_plan_executor.py)
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep, variables: dict[str, str] | None = None) -> Plan:
    return Plan(
        version=1,
        goal="test plan",
        steps=list(steps),
        variables=variables or {},
    )


def _make_run_state(plan: Plan, tmp_path: Path) -> RunState:
    log_path = tmp_path / "run_log.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(
        plan_path=str(tmp_path / "plan.json"),
        plan_version=plan.version,
        started_at="2025-01-01T00:00:00+00:00",
        status="running",
        executor_version="1.0.0",
    )
    write_run_log(log, log_path)
    return RunState(
        plan=plan,
        log=log,
        log_path=log_path,
        artifacts_dir=artifacts_dir,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubplan:
    def test_subplan_missing_path_fails(self, tmp_path: Path) -> None:
        step = PlanStep(id="sub1", type="subplan", prompt="nested")
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.failed

    def test_subplan_file_not_found_fails(self, tmp_path: Path) -> None:
        step = PlanStep(
            id="sub1", type="subplan", prompt="nested",
            subplan_path="/nonexistent.json",
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.failed

    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_success(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        # Create a sub-plan file
        sub_plan = {
            "version": 1,
            "goal": "sub",
            "steps": [
                {
                    "id": "inner",
                    "type": "task",
                    "prompt": "do inner work",
                    "agent_type": "worker",
                },
            ],
        }
        sub_path = tmp_path / "sub_plan.json"
        sub_path.write_text(json.dumps(sub_plan))

        step = PlanStep(
            id="sub1", type="subplan", prompt="nested",
            subplan_path=str(sub_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.completed

    def test_subplan_path_in_to_dict(self) -> None:
        step = PlanStep(id="s1", type="subplan", prompt="p", subplan_path="sub.json")
        d = step.to_dict()
        assert d["subplan_path"] == "sub.json"

    def test_subplan_path_not_in_to_dict_when_empty(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        d = step.to_dict()
        assert "subplan_path" not in d
