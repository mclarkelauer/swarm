"""Tests for swarm.plan.executor: RunState, execute_plan, record_*, finalize."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.executor import (
    RunState,
    StepExecution,
    execute_foreground,
    execute_plan,
    finalize,
    handle_checkpoint,
    handle_decision,
    handle_join,
    init_run_state,
    record_failure,
    record_skip,
    record_success,
)
from swarm.plan.models import (
    CheckpointConfig,
    ConditionalAction,
    DecisionConfig,
    LoopConfig,
    Plan,
    PlanStep,
    RetryConfig,
)
from swarm.plan.run_log import RunLog, StepOutcome, load_run_log, write_run_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep, variables: dict[str, str] | None = None) -> Plan:
    return Plan(
        version=1,
        goal="test plan",
        steps=list(steps),
        variables=variables or {},
    )


def _task(
    step_id: str,
    depends_on: tuple[str, ...] = (),
    on_failure: str = "stop",
    spawn_mode: str = "foreground",
    **kwargs: Any,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        type="task",
        prompt=f"Do {step_id}",
        agent_type="worker",
        depends_on=depends_on,
        on_failure=on_failure,
        spawn_mode=spawn_mode,
        **kwargs,
    )


def _make_run_state(
    plan: Plan,
    tmp_path: Path,
) -> RunState:
    """Create a RunState with a fresh RunLog, writing the initial log."""
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


def _mock_popen(exit_code: int = 0) -> MagicMock:
    """Return a mock Popen that returns the given exit_code on wait()."""
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 12345
    proc.wait.return_value = exit_code
    proc.poll.return_value = None
    return proc


# ---------------------------------------------------------------------------
# StepExecution dataclass
# ---------------------------------------------------------------------------


class TestStepExecution:
    def test_roundtrip(self) -> None:
        se = StepExecution(
            step_id="s1",
            attempt=1,
            agent_type="worker",
            pid=9999,
            started_at="2025-01-01T00:00:00+00:00",
            finished_at="2025-01-01T00:01:00+00:00",
            exit_code=0,
            output_artifact="out.md",
        )
        d = se.to_dict()
        restored = StepExecution.from_dict(d)
        assert restored.step_id == "s1"
        assert restored.attempt == 1
        assert restored.exit_code == 0
        assert restored.output_artifact == "out.md"

    def test_sparse_serialization(self) -> None:
        se = StepExecution(
            step_id="s1",
            attempt=0,
            agent_type="worker",
            pid=100,
            started_at="t0",
        )
        d = se.to_dict()
        assert "finished_at" not in d
        assert "exit_code" not in d
        assert "output_artifact" not in d
        assert "is_critic" not in d

    def test_critic_fields_serialized(self) -> None:
        se = StepExecution(
            step_id="s1",
            attempt=0,
            agent_type="reviewer",
            pid=100,
            started_at="t0",
            is_critic=True,
            critic_iteration=2,
        )
        d = se.to_dict()
        assert d["is_critic"] is True
        assert d["critic_iteration"] == 2


# ---------------------------------------------------------------------------
# init_run_state
# ---------------------------------------------------------------------------


class TestInitRunState:
    def test_creates_fresh_state(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        art_dir = tmp_path / "artifacts"

        rs = init_run_state(plan, plan_path, art_dir, log_path)

        assert rs.plan is plan
        assert rs.log.status == "running"
        assert rs.completed == set()
        assert rs.failed == set()
        assert rs.skipped == set()
        assert art_dir.exists()
        assert log_path.exists()

    def test_resumes_from_run_log(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"), _task("s2", depends_on=("s1",)))
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        art_dir = tmp_path / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        # Write a log with s1 completed
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2025-01-01T00:00:00+00:00",
            status="paused",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="t0",
                    finished_at="t1",
                ),
            ],
        )
        write_run_log(log, log_path)

        rs = init_run_state(plan, plan_path, art_dir, log_path)

        assert "s1" in rs.completed
        assert rs.step_outcomes["s1"] == "completed"
        assert rs.log.status == "running"

    def test_resumes_from_checkpoint(self, tmp_path: Path) -> None:
        plan = _plan(
            _task("s1"),
            PlanStep(
                id="cp",
                type="checkpoint",
                prompt="review",
                depends_on=("s1",),
            ),
            _task("s2", depends_on=("cp",)),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        art_dir = tmp_path / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="t0",
            status="paused",
            checkpoint_step_id="cp",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="t0",
                    finished_at="t1",
                ),
            ],
        )
        write_run_log(log, log_path)

        rs = init_run_state(plan, plan_path, art_dir, log_path)

        # Checkpoint step should be marked completed on resume
        assert "cp" in rs.completed
        assert rs.step_outcomes["cp"] == "completed"
        # checkpoint_step_id cleared
        assert rs.log.checkpoint_step_id == ""

    def test_corrupt_run_log_creates_fresh(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        log_path.write_text("not valid json", encoding="utf-8")
        art_dir = tmp_path / "artifacts"

        rs = init_run_state(plan, plan_path, art_dir, log_path)

        assert rs.completed == set()
        assert rs.log.status == "running"


# ---------------------------------------------------------------------------
# record_success / record_failure / record_skip
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_updates_run_state(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        record_success(rs, plan.steps[0], attempt=0, message="done")

        assert "s1" in rs.completed
        assert rs.step_outcomes["s1"] == "completed"
        assert len(rs.log.steps) == 1
        assert rs.log.steps[0].status == "completed"
        assert rs.log.steps[0].exit_code == 0

    def test_writes_log_file(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        record_success(rs, plan.steps[0], attempt=0)

        loaded = load_run_log(rs.log_path)
        assert len(loaded.steps) == 1
        assert loaded.steps[0].status == "completed"


class TestRecordFailure:
    def test_updates_run_state(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        record_failure(rs, plan.steps[0], attempt=0, message="boom", exit_code=1)

        assert "s1" in rs.failed
        assert rs.step_outcomes["s1"] == "failed"
        assert len(rs.log.steps) == 1
        assert rs.log.steps[0].status == "failed"
        assert rs.log.steps[0].exit_code == 1

    def test_records_attempt_number(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        record_failure(rs, plan.steps[0], attempt=2, message="retry exhausted")

        assert rs.log.steps[0].attempt == 2


class TestRecordSkip:
    def test_updates_run_state(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        record_skip(rs, plan.steps[0], attempt=0, message="skipped it")

        assert "s1" in rs.skipped
        assert rs.step_outcomes["s1"] == "skipped"
        assert len(rs.log.steps) == 1
        assert rs.log.steps[0].status == "skipped"


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


class TestFinalize:
    def test_writes_run_log(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("s1")
        rs.step_outcomes["s1"] = "completed"

        result = finalize(rs, "completed")

        assert result["status"] == "completed"
        assert result["steps_executed"] == 1
        assert result["steps_remaining"] == 0
        assert "s1" in result["completed_step_ids"]
        assert result["errors"] == []

        loaded = load_run_log(rs.log_path)
        assert loaded.status == "completed"
        assert loaded.finished_at != ""

    def test_reports_remaining_steps(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"), _task("s2", depends_on=("s1",)))
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("s1")
        rs.step_outcomes["s1"] = "completed"

        result = finalize(rs, "paused")

        assert result["steps_executed"] == 1
        assert result["steps_remaining"] == 1

    def test_failed_status(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"), _task("s2", depends_on=("s1",)))
        rs = _make_run_state(plan, tmp_path)
        rs.failed.add("s1")
        rs.step_outcomes["s1"] = "failed"

        result = finalize(rs, "failed")

        assert result["status"] == "failed"
        assert "s1" in result["failed_step_ids"]
        assert result["steps_remaining"] == 1  # s2 never ran

    def test_checkpoint_message(self, tmp_path: Path) -> None:
        ckpt_step = PlanStep(
            id="cp",
            type="checkpoint",
            prompt="check this",
            checkpoint_config=CheckpointConfig(message="Review the output"),
        )
        plan = _plan(_task("s1"), ckpt_step)
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("s1")
        rs.step_outcomes["s1"] = "completed"
        rs.log.checkpoint_step_id = "cp"

        result = finalize(rs, "paused")

        assert result["checkpoint_message"] == "Review the output"

    def test_skipped_step_ids(self, tmp_path: Path) -> None:
        plan = _plan(_task("s1"), _task("s2"))
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("s1")
        rs.step_outcomes["s1"] = "completed"
        rs.skipped.add("s2")
        rs.step_outcomes["s2"] = "skipped"

        result = finalize(rs, "completed")

        assert "s2" in result["skipped_step_ids"]
        assert result["steps_remaining"] == 0


# ---------------------------------------------------------------------------
# execute_plan — main loop
# ---------------------------------------------------------------------------


class TestExecutePlan:
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_single_step_success(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert "s1" in result["completed_step_ids"]

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_single_step_failure(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=1)
        mock_launch.return_value = proc

        plan = _plan(_task("s1"))
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "failed"
        assert "s1" in result["failed_step_ids"]

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_linear_dag_runs_in_order(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            _task("s2", depends_on=("s1",)),
            _task("s3", depends_on=("s2",)),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert set(result["completed_step_ids"]) == {"s1", "s2", "s3"}
        # launch_agent called 3 times
        assert mock_launch.call_count == 3

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_parallel_steps_detected(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Steps without mutual dependencies should both be dispatched."""
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            _task("s2"),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert set(result["completed_step_ids"]) == {"s1", "s2"}

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_max_steps_pauses(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            _task("s2"),
            _task("s3"),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs, max_steps=1)

        assert result["status"] == "paused"
        assert result["steps_executed"] >= 1
        # Not all steps completed
        assert result["steps_remaining"] > 0

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_checkpoint_pauses(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            PlanStep(
                id="cp",
                type="checkpoint",
                prompt="review",
                depends_on=("s1",),
                checkpoint_config=CheckpointConfig(message="Please review"),
            ),
            _task("s2", depends_on=("cp",)),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "paused"
        loaded = load_run_log(rs.log_path)
        assert loaded.checkpoint_step_id == "cp"

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_checkpoint_resume(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After a checkpoint pause, reinitializing and executing should resume."""
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            PlanStep(
                id="cp",
                type="checkpoint",
                prompt="review",
                depends_on=("s1",),
                checkpoint_config=CheckpointConfig(message="Pause here"),
            ),
            _task("s2", depends_on=("cp",)),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        art_dir = tmp_path / "artifacts"

        # First run: executes s1, pauses at checkpoint
        rs = init_run_state(plan, plan_path, art_dir, log_path)
        result1 = execute_plan(rs)
        assert result1["status"] == "paused"

        # Resume: should continue from checkpoint and complete s2
        rs2 = init_run_state(plan, plan_path, art_dir, log_path)
        result2 = execute_plan(rs2)

        assert result2["status"] == "completed"
        assert "s2" in result2["completed_step_ids"]

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_completed_status(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(_task("s1"), _task("s2", depends_on=("s1",)))
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert result["steps_remaining"] == 0

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_failed_status(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=1)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            _task("s2", depends_on=("s1",)),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        # s1 fails with on_failure=stop, so plan fails
        assert result["status"] == "failed"
        assert "s1" in result["failed_step_ids"]

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_on_failure_stop_halts_plan(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=1)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1", on_failure="stop"),
            _task("s2", depends_on=("s1",)),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "failed"
        assert "s2" not in result["completed_step_ids"]
        # launch_agent only called once for s1
        assert mock_launch.call_count == 1

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_on_failure_skip_continues(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")

        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_popen(exit_code=1)
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _side_effect

        plan = _plan(
            _task("s1", on_failure="skip"),
            _task("s2"),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert "s1" in result["skipped_step_ids"]
        assert "s2" in result["completed_step_ids"]

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_handle_join_runs_as_task(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Join steps execute as foreground tasks."""
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("s1"),
            _task("s2"),
            PlanStep(
                id="j1",
                type="join",
                prompt="combine results",
                agent_type="merger",
                depends_on=("s1", "s2"),
            ),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert "j1" in result["completed_step_ids"]


# ---------------------------------------------------------------------------
# handle_decision
# ---------------------------------------------------------------------------


class TestHandleDecision:
    def test_decision_skips_downstream(self, tmp_path: Path) -> None:
        """Decision step can skip downstream steps."""
        plan = _plan(
            _task("build"),
            PlanStep(
                id="decide",
                type="decision",
                prompt="branch",
                depends_on=("build",),
                decision_config=DecisionConfig(
                    actions=(
                        ConditionalAction(
                            condition="step_completed:build",
                            skip_steps=("deploy",),
                        ),
                    ),
                ),
            ),
            _task("deploy", depends_on=("decide",)),
        )
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("build")
        rs.step_outcomes["build"] = "completed"

        step = plan.steps[1]  # "decide"
        handle_decision(rs, step)

        assert "decide" in rs.completed
        assert "deploy" in rs.skipped
        assert rs.step_outcomes["deploy"] == "skipped"

    def test_decision_activates_steps(self, tmp_path: Path) -> None:
        """Decision step can activate steps by overriding conditions."""
        plan = _plan(
            _task("build"),
            PlanStep(
                id="decide",
                type="decision",
                prompt="branch",
                depends_on=("build",),
                decision_config=DecisionConfig(
                    actions=(
                        ConditionalAction(
                            condition="step_completed:build",
                            activate_steps=("fix-deps",),
                        ),
                    ),
                ),
            ),
            PlanStep(
                id="fix-deps",
                type="task",
                prompt="fix dependencies",
                agent_type="fixer",
                depends_on=("decide",),
                condition="never",
            ),
        )
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("build")
        rs.step_outcomes["build"] = "completed"

        step = plan.steps[1]  # "decide"
        handle_decision(rs, step)

        assert "decide" in rs.completed
        assert "fix-deps" in rs.decision_overrides
        assert rs.decision_overrides["fix-deps"] == ""

    def test_decision_missing_config_fails(self, tmp_path: Path) -> None:
        """Decision step without config records failure."""
        plan = _plan(
            PlanStep(id="decide", type="decision", prompt="branch"),
        )
        rs = _make_run_state(plan, tmp_path)

        handle_decision(rs, plan.steps[0])

        assert "decide" in rs.failed
        assert rs.step_outcomes["decide"] == "failed"

    def test_decision_condition_not_met(self, tmp_path: Path) -> None:
        """Decision actions whose condition is not met do not fire."""
        plan = _plan(
            _task("build"),
            PlanStep(
                id="decide",
                type="decision",
                prompt="branch",
                depends_on=("build",),
                decision_config=DecisionConfig(
                    actions=(
                        ConditionalAction(
                            condition="step_failed:build",
                            skip_steps=("build",),
                        ),
                    ),
                ),
            ),
        )
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("build")
        rs.step_outcomes["build"] = "completed"

        handle_decision(rs, plan.steps[1])

        # Decision completes successfully but no actions fire
        assert "decide" in rs.completed
        assert "build" not in rs.skipped

    def test_decision_with_output_contains(self, tmp_path: Path) -> None:
        """Decision step uses output_contains condition."""
        plan = _plan(
            _task("build"),
            PlanStep(
                id="decide",
                type="decision",
                prompt="check output",
                depends_on=("build",),
                decision_config=DecisionConfig(
                    actions=(
                        ConditionalAction(
                            condition="output_contains:build:ERROR.*missing",
                            activate_steps=("fix",),
                        ),
                    ),
                ),
            ),
            PlanStep(
                id="fix",
                type="task",
                prompt="fix",
                agent_type="fixer",
                depends_on=("decide",),
                condition="never",
            ),
        )
        rs = _make_run_state(plan, tmp_path)
        rs.completed.add("build")
        rs.step_outcomes["build"] = "completed"

        # Write a stdout log that matches
        (rs.artifacts_dir / "build.stdout.log").write_text(
            "ERROR: missing dependency foo", encoding="utf-8"
        )

        handle_decision(rs, plan.steps[1])

        assert "fix" in rs.decision_overrides


class TestExecutePlanWithDecision:
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_decision_skips_branch_and_activates_another(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """End-to-end: decision step skips one branch, activates another."""
        mock_find.return_value = Path("/usr/bin/claude")
        proc = _mock_popen(exit_code=0)
        mock_launch.return_value = proc

        plan = _plan(
            _task("build"),
            PlanStep(
                id="decide",
                type="decision",
                prompt="check build",
                depends_on=("build",),
                decision_config=DecisionConfig(
                    actions=(
                        ConditionalAction(
                            condition="step_completed:build",
                            activate_steps=("test",),
                            skip_steps=("fix",),
                        ),
                    ),
                ),
            ),
            PlanStep(
                id="fix",
                type="task",
                prompt="fix things",
                agent_type="fixer",
                depends_on=("decide",),
                condition="never",
            ),
            PlanStep(
                id="test",
                type="task",
                prompt="run tests",
                agent_type="tester",
                depends_on=("decide",),
                condition="never",
            ),
        )
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert "build" in result["completed_step_ids"]
        assert "decide" in result["completed_step_ids"]
        assert "test" in result["completed_step_ids"]
        assert "fix" in result["skipped_step_ids"]


class TestBuildAgentSystemPrompt:
    """Tests for _build_agent_system_prompt with memory injection."""

    def test_with_memory_injects_agent_memories(self, tmp_path: Path) -> None:
        from swarm.memory.api import MemoryAPI
        from swarm.plan.executor import _build_agent_system_prompt

        mem_api = MemoryAPI(tmp_path / "mem.db")
        mem_api.store("test-agent", "Always use pytest fixtures", memory_type="procedural")

        step = PlanStep(id="s1", type="task", prompt="do stuff", agent_type="test-agent")
        result = _build_agent_system_prompt(step, tmp_path, memory_api=mem_api)

        assert "<agent-memory>" in result
        assert "Always use pytest fixtures" in result

    def test_without_memory_api_no_memory_block(self, tmp_path: Path) -> None:
        from swarm.plan.executor import _build_agent_system_prompt

        step = PlanStep(id="s1", type="task", prompt="do stuff", agent_type="test-agent")
        result = _build_agent_system_prompt(step, tmp_path, memory_api=None)

        assert "<agent-memory>" not in result

    def test_no_agent_type_skips_memory(self, tmp_path: Path) -> None:
        from swarm.memory.api import MemoryAPI
        from swarm.plan.executor import _build_agent_system_prompt

        mem_api = MemoryAPI(tmp_path / "mem.db")
        mem_api.store("test-agent", "some memory")

        step = PlanStep(id="s1", type="task", prompt="do stuff")
        result = _build_agent_system_prompt(step, tmp_path, memory_api=mem_api)

        assert "<agent-memory>" not in result

    def test_empty_memories_no_block(self, tmp_path: Path) -> None:
        from swarm.memory.api import MemoryAPI
        from swarm.plan.executor import _build_agent_system_prompt

        mem_api = MemoryAPI(tmp_path / "mem.db")
        # No memories stored for this agent

        step = PlanStep(id="s1", type="task", prompt="do stuff", agent_type="other-agent")
        result = _build_agent_system_prompt(step, tmp_path, memory_api=mem_api)

        assert "<agent-memory>" not in result


class TestTimeoutPassthrough:
    """Tests that per-step timeout is threaded to wait_with_timeout."""

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_timeout_passed_when_set(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_proc = MagicMock()
        mock_launch.return_value = mock_proc
        mock_wait.return_value = 0

        step = PlanStep(
            id="s1", type="task", prompt="p", agent_type="worker", timeout=120,
        )
        plan = Plan(version=1, goal="test", steps=[step])
        rs = _make_run_state(plan, tmp_path)
        execute_foreground(rs, step)

        mock_wait.assert_called_once_with(mock_proc, timeout=120)

    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_no_timeout_when_zero(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_proc = MagicMock()
        mock_launch.return_value = mock_proc
        mock_wait.return_value = 0

        step = PlanStep(
            id="s1", type="task", prompt="p", agent_type="worker", timeout=0,
        )
        plan = Plan(version=1, goal="test", steps=[step])
        rs = _make_run_state(plan, tmp_path)
        execute_foreground(rs, step)

        mock_wait.assert_called_once_with(mock_proc, timeout=None)
