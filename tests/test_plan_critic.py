"""Tests for critic loop execution in swarm.plan.executor."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.executor import (
    CriticResult,
    RunState,
    _read_verdict,
    execute_foreground,
    run_critic_loop,
)
from swarm.plan.models import Plan, PlanStep
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


def _step_with_critic(
    step_id: str = "s1",
    critic_agent: str = "code-reviewer",
    max_critic_iterations: int = 3,
    on_failure: str = "stop",
    **kwargs: Any,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        type="task",
        prompt="do work",
        agent_type="worker",
        output_artifact="output.md",
        critic_agent=critic_agent,
        max_critic_iterations=max_critic_iterations,
        on_failure=on_failure,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# CriticResult
# ---------------------------------------------------------------------------


class TestCriticResult:
    def test_approved_result(self) -> None:
        cr = CriticResult(approved=True, feedback="Looks good")
        assert cr.approved is True
        assert cr.feedback == "Looks good"

    def test_rejected_result(self) -> None:
        cr = CriticResult(approved=False, feedback="Needs work")
        assert cr.approved is False
        assert cr.feedback == "Needs work"

    def test_default_feedback(self) -> None:
        cr = CriticResult(approved=True)
        assert cr.feedback == ""

    def test_frozen(self) -> None:
        cr = CriticResult(approved=True)
        with pytest.raises(AttributeError):
            cr.approved = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _read_verdict
# ---------------------------------------------------------------------------


class TestReadVerdict:
    def test_missing_verdict_file_fails_open(self, tmp_path: Path) -> None:
        result = _read_verdict(tmp_path, "output.md")
        assert result.approved is True
        assert "fail-open" in result.feedback.lower() or "No verdict" in result.feedback

    def test_valid_approved_verdict(self, tmp_path: Path) -> None:
        verdict_path = tmp_path / "output.md.verdict.json"
        verdict_path.write_text(
            json.dumps({"approved": True, "feedback": "All clear"}),
            encoding="utf-8",
        )
        result = _read_verdict(tmp_path, "output.md")
        assert result.approved is True
        assert result.feedback == "All clear"

    def test_valid_rejected_verdict(self, tmp_path: Path) -> None:
        verdict_path = tmp_path / "output.md.verdict.json"
        verdict_path.write_text(
            json.dumps({"approved": False, "feedback": "Missing tests"}),
            encoding="utf-8",
        )
        result = _read_verdict(tmp_path, "output.md")
        assert result.approved is False
        assert result.feedback == "Missing tests"

    def test_malformed_json_fails_open(self, tmp_path: Path) -> None:
        verdict_path = tmp_path / "output.md.verdict.json"
        verdict_path.write_text("not json at all", encoding="utf-8")
        result = _read_verdict(tmp_path, "output.md")
        assert result.approved is True
        assert "fail-open" in result.feedback.lower()

    def test_missing_approved_field_defaults_true(self, tmp_path: Path) -> None:
        verdict_path = tmp_path / "output.md.verdict.json"
        verdict_path.write_text(
            json.dumps({"feedback": "some feedback"}),
            encoding="utf-8",
        )
        result = _read_verdict(tmp_path, "output.md")
        assert result.approved is True


# ---------------------------------------------------------------------------
# run_critic_loop
# ---------------------------------------------------------------------------


class TestRunCriticLoop:
    @patch("swarm.plan.executor.launch_agent")
    def test_approves_on_first_pass(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Critic approves immediately on first pass."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        # Write approval verdict before critic runs
        verdict_path = rs.artifacts_dir / "output.md.verdict.json"
        verdict_path.write_text(
            json.dumps({"approved": True, "feedback": "LGTM"}),
            encoding="utf-8",
        )

        result = run_critic_loop(rs, step)

        assert result.approved is True
        # Only 1 call: the critic
        assert mock_launch.call_count == 1

    @patch("swarm.plan.executor.launch_agent")
    def test_rejects_then_approves(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Critic rejects once, then approves on revision."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        verdict_path = rs.artifacts_dir / "output.md.verdict.json"
        call_count = 0

        def _launch_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            proc = _mock_popen(exit_code=0)
            if call_count == 1:
                # First critic pass: reject
                verdict_path.write_text(
                    json.dumps({"approved": False, "feedback": "Add tests"}),
                    encoding="utf-8",
                )
            elif call_count == 3:
                # Second critic pass (after revision): approve
                verdict_path.write_text(
                    json.dumps({"approved": True, "feedback": "Good now"}),
                    encoding="utf-8",
                )
            # call_count 2 is the revision agent
            return proc

        mock_launch.side_effect = _launch_side_effect

        result = run_critic_loop(rs, step)

        assert result.approved is True
        # 3 calls: critic -> revision -> critic
        assert mock_launch.call_count == 3

    @patch("swarm.plan.executor.launch_agent")
    def test_exhausts_iterations(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Critic never approves -- exhausts max iterations."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=2)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        verdict_path = rs.artifacts_dir / "output.md.verdict.json"

        def _launch_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            # Always write rejected verdict
            verdict_path.write_text(
                json.dumps({"approved": False, "feedback": "Still bad"}),
                encoding="utf-8",
            )
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _launch_side_effect

        result = run_critic_loop(rs, step)

        assert result.approved is False
        assert "2" in result.feedback or "Not approved" in result.feedback

    @patch("swarm.plan.executor.launch_agent")
    def test_critic_process_failed_fails_open(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If the critic process itself fails (non-zero exit), fail-open."""
        mock_launch.return_value = _mock_popen(exit_code=1)

        step = _step_with_critic(max_critic_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        result = run_critic_loop(rs, step)

        assert result.approved is True
        assert "fail-open" in result.feedback.lower()

    @patch("swarm.plan.executor.launch_agent")
    def test_missing_verdict_file_fails_open(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If the critic does not create a verdict file, fail-open."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        # Do NOT create the verdict file

        result = run_critic_loop(rs, step)

        assert result.approved is True

    @patch("swarm.plan.executor.launch_agent")
    def test_malformed_verdict_fails_open(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Malformed verdict file should fail-open."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=3)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        verdict_path = rs.artifacts_dir / "output.md.verdict.json"
        verdict_path.write_text("{{{{not json}}}", encoding="utf-8")

        result = run_critic_loop(rs, step)

        assert result.approved is True


# ---------------------------------------------------------------------------
# execute_foreground with critic integration
# ---------------------------------------------------------------------------


class TestExecuteForegroundWithCritic:
    @patch("swarm.plan.executor.launch_agent")
    def test_critic_approval_records_success(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Step with critic: success on main + critic approval = overall success."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic()
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        verdict_path = rs.artifacts_dir / "output.md.verdict.json"
        verdict_path.write_text(
            json.dumps({"approved": True, "feedback": "OK"}),
            encoding="utf-8",
        )

        execute_foreground(rs, step)

        assert "s1" in rs.completed

    @patch("swarm.plan.executor.launch_agent")
    def test_critic_rejection_records_failure(
        self,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Step with critic: critic rejects and on_failure=stop => failure."""
        mock_launch.return_value = _mock_popen(exit_code=0)

        step = _step_with_critic(max_critic_iterations=1, on_failure="stop")
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        verdict_path = rs.artifacts_dir / "output.md.verdict.json"

        def _launch_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            verdict_path.write_text(
                json.dumps({"approved": False, "feedback": "Bad"}),
                encoding="utf-8",
            )
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _launch_side_effect

        execute_foreground(rs, step)

        assert "s1" in rs.failed
        assert "Critic rejected" in rs.log.steps[-1].message
