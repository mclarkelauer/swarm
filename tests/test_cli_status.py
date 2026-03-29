"""Tests for the ``swarm status`` command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, StepOutcome, write_run_log


def _make_run_log(tmp_path: Path, plan_path: str = "plan_v1.json") -> Path:
    """Write a completed run log to tmp_path and return its path."""
    log = RunLog(
        plan_path=plan_path,
        plan_version=1,
        started_at="2026-01-01T10:00:00+00:00",
        finished_at="2026-01-01T10:05:30+00:00",
        status="completed",
        steps=[
            StepOutcome(
                step_id="s1",
                status="completed",
                started_at="2026-01-01T10:00:00+00:00",
                finished_at="2026-01-01T10:02:00+00:00",
            ),
            StepOutcome(
                step_id="s2",
                status="completed",
                started_at="2026-01-01T10:02:00+00:00",
                finished_at="2026-01-01T10:05:30+00:00",
                message="Deployed successfully",
            ),
        ],
    )
    log_path = tmp_path / "run_log.json"
    write_run_log(log, log_path)
    return log_path


def _make_plan_file(tmp_path: Path) -> Path:
    plan = Plan(
        version=1,
        goal="test goal",
        steps=[
            PlanStep(id="s1", type="task", prompt="first step", agent_type="worker"),
            PlanStep(
                id="s2",
                type="task",
                prompt="second step",
                agent_type="deployer",
                depends_on=("s1",),
            ),
        ],
    )
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    return path


class TestStatusMissingLog:
    def test_missing_run_log_shows_friendly_message(self, tmp_path: Path) -> None:
        runner = CliRunner()
        missing = tmp_path / "run_log.json"
        result = runner.invoke(cli, ["status", "--log-file", str(missing)])
        assert result.exit_code == 0
        # Should not crash; should print a friendly message
        assert "No run log found" in result.output or "not found" in result.output.lower()

    def test_default_run_log_missing_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        # Run from tmp_path so default run_log.json is not found there
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0


class TestStatusWithValidLog:
    def test_shows_plan_path_in_output(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        log_path = _make_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert str(plan_path) in result.output

    def test_shows_step_ids_in_table(self, tmp_path: Path) -> None:
        log_path = _make_run_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "s1" in result.output
        assert "s2" in result.output

    def test_shows_plan_version(self, tmp_path: Path) -> None:
        log_path = _make_run_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "1" in result.output  # version number

    def test_shows_overall_status(self, tmp_path: Path) -> None:
        log_path = _make_run_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "completed" in result.output

    def test_shows_progress(self, tmp_path: Path) -> None:
        log_path = _make_run_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        # "2/2 steps complete" or similar
        assert "2" in result.output

    def test_shows_step_message(self, tmp_path: Path) -> None:
        log_path = _make_run_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "Deployed successfully" in result.output

    def test_cross_references_plan_for_agent_type(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        log_path = _make_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        # agent types from the plan should appear
        assert "worker" in result.output
        assert "deployer" in result.output

    def test_custom_log_file_path(self, tmp_path: Path) -> None:
        custom_log = tmp_path / "custom_log.json"
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=2,
            started_at="2026-01-01T10:00:00+00:00",
            status="running",
            steps=[
                StepOutcome(
                    step_id="step-a",
                    status="completed",
                    started_at="2026-01-01T10:00:00+00:00",
                    finished_at="2026-01-01T10:01:00+00:00",
                ),
            ],
        )
        write_run_log(log, custom_log)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(custom_log)])
        assert result.exit_code == 0
        assert "step-a" in result.output


class TestStatusWithRunningLog:
    def test_running_status_shown(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=1,
            started_at="2026-01-01T10:00:00+00:00",
            status="running",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="2026-01-01T10:00:00+00:00",
                    finished_at="2026-01-01T10:01:00+00:00",
                ),
            ],
        )
        log_path = tmp_path / "run_log.json"
        write_run_log(log, log_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "running" in result.output

    def test_empty_steps_shows_no_outcomes_message(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=1,
            started_at="2026-01-01T10:00:00+00:00",
            status="running",
            steps=[],
        )
        log_path = tmp_path / "run_log.json"
        write_run_log(log, log_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        # Should mention no steps recorded
        assert "No step outcomes" in result.output or "0" in result.output


# ---------------------------------------------------------------------------
# Helper factories for diagnose tests
# ---------------------------------------------------------------------------


def _make_failed_run_log(
    tmp_path: Path,
    plan_path: str,
    run_status: str = "failed",
    failed_step_id: str = "s2",
    error_message: str = "Connection refused",
    on_failure_override: str | None = None,
) -> Path:
    """Write a run log in the given status with one completed and one failed step."""
    steps = [
        StepOutcome(
            step_id="s1",
            status="completed",
            started_at="2026-01-01T10:00:00+00:00",
            finished_at="2026-01-01T10:01:00+00:00",
        ),
        StepOutcome(
            step_id=failed_step_id,
            status="failed",
            started_at="2026-01-01T10:01:00+00:00",
            finished_at="2026-01-01T10:01:30+00:00",
            message=error_message,
        ),
    ]
    log = RunLog(
        plan_path=plan_path,
        plan_version=1,
        started_at="2026-01-01T10:00:00+00:00",
        finished_at="2026-01-01T10:01:30+00:00",
        status=run_status,
        steps=steps,
    )
    log_path = tmp_path / "run_log.json"
    write_run_log(log, log_path)
    return log_path


def _make_plan_with_on_failure(
    tmp_path: Path,
    on_failure: str = "stop",
    add_downstream: bool = True,
) -> Path:
    """Write a plan file with configurable on_failure for s2."""
    steps: list[PlanStep] = [
        PlanStep(id="s1", type="task", prompt="first", agent_type="worker"),
        PlanStep(
            id="s2",
            type="task",
            prompt="second",
            agent_type="deployer",
            depends_on=("s1",),
            on_failure=on_failure,
        ),
    ]
    if add_downstream:
        steps.append(
            PlanStep(
                id="s3",
                type="task",
                prompt="third",
                agent_type="notifier",
                depends_on=("s2",),
            )
        )
    plan = Plan(version=1, goal="test goal", steps=steps)
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test classes for --diagnose
# ---------------------------------------------------------------------------


class TestDiagnoseCompletedRun:
    """--diagnose on a completed run prints the no-failures message."""

    def test_diagnose_completed_shows_no_failures(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        log_path = _make_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "No failures to diagnose" in result.output

    def test_diagnose_running_shows_no_failures(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=1,
            started_at="2026-01-01T10:00:00+00:00",
            status="running",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="2026-01-01T10:00:00+00:00",
                    finished_at="2026-01-01T10:01:00+00:00",
                ),
            ],
        )
        log_path = tmp_path / "run_log.json"
        write_run_log(log, log_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "No failures to diagnose" in result.output


class TestDiagnoseFailedRun:
    """--diagnose on a failed run shows failure details."""

    def test_shows_failed_step_id(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "s2" in result.output

    def test_shows_error_message(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path)
        log_path = _make_failed_run_log(
            tmp_path, plan_path=str(plan_path), error_message="Connection refused"
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "Connection refused" in result.output

    def test_shows_agent_type_from_plan(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "deployer" in result.output

    def test_shows_blocked_downstream_steps(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, add_downstream=True)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        # s3 depends on s2 (failed) and is not completed
        assert "s3" in result.output

    def test_completed_steps_not_in_blocked_list(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, add_downstream=True)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        # s1 is completed so it should not appear in the blocked list under "Blocked"
        # (it does appear in the regular table, but we check blocked section specifically)
        output_lower = result.output
        # Verify diagnose section mentions s3 as blocked, not s1
        diagnose_section = output_lower[output_lower.find("Failure Diagnosis"):]
        assert "s3" in diagnose_section
        # s1 is not blocked (it completed successfully)
        blocked_index = diagnose_section.find("Blocked downstream")
        if blocked_index != -1:
            blocked_text = diagnose_section[blocked_index: blocked_index + 200]
            assert "s1" not in blocked_text

    def test_shows_on_stop_suggestion(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, on_failure="stop")
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "plan_amend" in result.output
        assert "s2" in result.output

    def test_shows_on_retry_suggestion(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, on_failure="retry")
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "retry" in result.output.lower()
        assert "max retries" in result.output

    def test_shows_on_skip_suggestion(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, on_failure="skip")
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()
        assert "missing inputs" in result.output

    def test_diagnose_section_shows_header(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "Failure Diagnosis" in result.output


class TestDiagnosePausedRun:
    """--diagnose on a paused run."""

    def test_paused_with_no_failures_shows_checkpoint_message(
        self, tmp_path: Path
    ) -> None:
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=1,
            started_at="2026-01-01T10:00:00+00:00",
            status="paused",
            steps=[
                StepOutcome(
                    step_id="s1",
                    status="completed",
                    started_at="2026-01-01T10:00:00+00:00",
                    finished_at="2026-01-01T10:01:00+00:00",
                ),
            ],
        )
        log_path = tmp_path / "run_log.json"
        write_run_log(log, log_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "paused" in result.output.lower()
        assert "checkpoint" in result.output.lower()

    def test_paused_with_failed_steps_shows_diagnosis(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path, on_failure="stop")
        log_path = _make_failed_run_log(
            tmp_path, plan_path=str(plan_path), run_status="paused"
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        assert "Failure Diagnosis" in result.output
        assert "s2" in result.output


class TestDiagnoseMissingPlanFile:
    """--diagnose when the plan file referenced by the run log is absent."""

    def test_missing_plan_shows_basic_info(self, tmp_path: Path) -> None:
        # Use a non-existent plan path
        log_path = _make_failed_run_log(
            tmp_path,
            plan_path=str(tmp_path / "nonexistent_plan.json"),
            error_message="Timeout after 30s",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        # Should still show the failed step id
        assert "s2" in result.output
        # Should show the error message
        assert "Timeout after 30s" in result.output

    def test_missing_plan_shows_warning(self, tmp_path: Path) -> None:
        log_path = _make_failed_run_log(
            tmp_path, plan_path=str(tmp_path / "nonexistent_plan.json")
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        # Should indicate plan file is missing
        assert "not found" in result.output.lower() or "Plan file" in result.output

    def test_missing_plan_still_shows_suggestion(self, tmp_path: Path) -> None:
        log_path = _make_failed_run_log(
            tmp_path, plan_path=str(tmp_path / "nonexistent_plan.json")
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["status", "--log-file", str(log_path), "--diagnose"]
        )
        assert result.exit_code == 0
        # Default (stop) suggestion should appear even without plan context
        assert "plan_amend" in result.output


class TestDiagnoseWithoutFlag:
    """Without --diagnose, no diagnosis section is printed."""

    def test_no_diagnose_section_without_flag(self, tmp_path: Path) -> None:
        plan_path = _make_plan_with_on_failure(tmp_path)
        log_path = _make_failed_run_log(tmp_path, plan_path=str(plan_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--log-file", str(log_path)])
        assert result.exit_code == 0
        assert "Failure Diagnosis" not in result.output
        assert "plan_amend" not in result.output
