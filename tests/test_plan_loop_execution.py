"""Tests for loop step handling in swarm.plan.executor.handle_loop."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.conditions import evaluate_condition, validate_condition
from swarm.plan.executor import RunState, handle_loop
from swarm.plan.models import LoopConfig, Plan, PlanStep
from swarm.plan.run_log import RunLog, write_run_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep) -> Plan:
    return Plan(version=1, goal="test", steps=list(steps))


def _make_run_state(plan: Plan, tmp_path: Path) -> RunState:
    log_path = tmp_path / "run_log.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(
        plan_path=str(tmp_path / "plan.json"),
        plan_version=1,
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


def _mock_popen(exit_code: int = 0) -> MagicMock:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 12345
    proc.wait.return_value = exit_code
    proc.poll.return_value = None
    return proc


def _loop_step(
    step_id: str = "loop1",
    condition: str = "",
    max_iterations: int = 5,
    **kwargs: Any,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        type="loop",
        prompt="iterate",
        agent_type="worker",
        loop_config=LoopConfig(
            condition=condition,
            max_iterations=max_iterations,
        ),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# handle_loop tests
# ---------------------------------------------------------------------------


class TestHandleLoop:
    @patch("swarm.plan.executor.launch_agent")
    def test_runs_until_max_iterations(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Loop without condition runs max_iterations times then succeeds."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _loop_step(max_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_loop(rs, step)

        assert "loop1" in rs.completed
        assert rs.loop_iterations["loop1"] == 3
        assert mock_launch.call_count == 3

    @patch("swarm.plan.executor.launch_agent")
    def test_body_failure_stops_loop(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If the loop body fails, the loop stops with failure."""
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return _mock_popen(exit_code=1)
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _side_effect

        step = _loop_step(max_iterations=5)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_loop(rs, step)

        assert "loop1" in rs.failed
        # Only 2 calls: first succeeded, second failed
        assert mock_launch.call_count == 2

    @patch("swarm.plan.executor.launch_agent")
    def test_condition_met_stops_loop(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Loop with iteration_ge condition stops when iteration threshold reached."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        # condition: iteration_ge:3 means the loop terminates when iteration >= 3
        step = _loop_step(condition="iteration_ge:3", max_iterations=10)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_loop(rs, step)

        assert "loop1" in rs.completed
        # Should have run 3 iterations (0, 1, 2) before condition triggers at iteration=3
        assert mock_launch.call_count == 3
        assert rs.loop_iterations["loop1"] == 3

    @patch("swarm.plan.executor.launch_agent")
    def test_artifact_exists_condition(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Loop with artifact_exists condition stops when artifact file appears."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            proc = _mock_popen(exit_code=0)
            # After second iteration, create the artifact
            if call_count == 2:
                (artifacts_dir / "done.txt").write_text("done", encoding="utf-8")
            return proc

        mock_launch.side_effect = _side_effect

        step = _loop_step(condition="artifact_exists:done.txt", max_iterations=10)
        plan = _plan(step)

        log_path = tmp_path / "run_log.json"
        log = RunLog(
            plan_path="plan.json",
            plan_version=1,
            started_at="t0",
            status="running",
        )
        write_run_log(log, log_path)
        rs = RunState(
            plan=plan,
            log=log,
            log_path=log_path,
            artifacts_dir=artifacts_dir,
        )

        handle_loop(rs, step)

        assert "loop1" in rs.completed
        # 2 iterations executed before the artifact exists
        assert mock_launch.call_count == 2

    def test_missing_loop_config_fails(self, tmp_path: Path) -> None:
        """A loop step without loop_config should record failure."""
        step = PlanStep(
            id="bad_loop",
            type="loop",
            prompt="iterate",
            agent_type="worker",
            # No loop_config!
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_loop(rs, step)

        assert "bad_loop" in rs.failed
        assert "loop_config" in rs.log.steps[0].message

    @patch("swarm.plan.executor.launch_agent")
    def test_loop_success_message_includes_iteration_count(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _loop_step(max_iterations=2)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_loop(rs, step)

        assert "loop1" in rs.completed
        last_outcome = rs.log.steps[-1]
        assert "max_iterations" in last_outcome.message or "2" in last_outcome.message


# ---------------------------------------------------------------------------
# iteration_ge condition tests
# ---------------------------------------------------------------------------


class TestIterationGeCondition:
    def test_validation_valid(self) -> None:
        assert validate_condition("iteration_ge:5") is None

    def test_validation_non_integer_is_error(self) -> None:
        error = validate_condition("iteration_ge:abc")
        assert error is not None
        assert "positive integer" in error

    def test_validation_zero_is_error(self) -> None:
        error = validate_condition("iteration_ge:0")
        assert error is not None
        assert "positive integer" in error

    def test_validation_negative_is_error(self) -> None:
        error = validate_condition("iteration_ge:-1")
        assert error is not None
        assert "positive integer" in error

    def test_validation_empty_value_is_error(self) -> None:
        error = validate_condition("iteration_ge:")
        assert error is not None
        assert "empty" in error.lower()

    def test_evaluation_below_threshold(self) -> None:
        assert evaluate_condition("iteration_ge:5", set(), iteration=3) is False

    def test_evaluation_at_threshold(self) -> None:
        assert evaluate_condition("iteration_ge:5", set(), iteration=5) is True

    def test_evaluation_above_threshold(self) -> None:
        assert evaluate_condition("iteration_ge:5", set(), iteration=10) is True

    def test_evaluation_none_iteration(self) -> None:
        assert evaluate_condition("iteration_ge:5", set(), iteration=None) is False

    def test_evaluation_default_iteration(self) -> None:
        # When iteration kwarg is not passed, defaults to None -> False
        assert evaluate_condition("iteration_ge:5", set()) is False

    def test_requires_positive_integer(self) -> None:
        error = validate_condition("iteration_ge:0")
        assert error is not None
        assert ">= 1" in error
