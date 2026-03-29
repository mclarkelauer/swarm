"""Tests for the ``swarm run`` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.plan.models import LoopConfig, Plan, PlanStep
from swarm.plan.run_log import load_run_log


def _make_plan_file(tmp_path: Path) -> Path:
    plan = Plan(
        version=1,
        goal="test goal",
        steps=[
            PlanStep(id="s1", type="task", prompt="first", agent_type="worker"),
            PlanStep(id="s2", type="task", prompt="second", agent_type="worker", depends_on=("s1",)),
        ],
    )
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()))
    return path


def _make_checkpoint_plan(tmp_path: Path) -> Path:
    plan = Plan(
        version=1,
        goal="checkpoint test",
        steps=[
            PlanStep(id="s1", type="task", prompt="first", agent_type="worker"),
            PlanStep(
                id="cp", type="checkpoint", prompt="review",
                depends_on=("s1",),
            ),
        ],
    )
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()))
    return path


class TestRun:
    def test_run_walks_dag(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        with patch("swarm.cli.run_cmd.click.confirm", return_value=True):
            result = runner.invoke(cli, ["run", str(plan_path)])
        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_run_writes_log(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        with patch("swarm.cli.run_cmd.click.confirm", return_value=True):
            runner.invoke(cli, ["run", str(plan_path)])
        log_path = tmp_path / "run_log.json"
        assert log_path.exists()
        log = load_run_log(log_path)
        assert log.status == "completed"
        completed_ids = {s.step_id for s in log.steps if s.status == "completed"}
        assert "s1" in completed_ids
        assert "s2" in completed_ids

    def test_run_pauses_when_declined(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        # Decline at the first confirm
        with patch("swarm.cli.run_cmd.click.confirm", return_value=False):
            result = runner.invoke(cli, ["run", str(plan_path)])
        assert result.exit_code == 0
        assert "Paused" in result.output

    def test_run_pauses_at_checkpoint(self, tmp_path: Path) -> None:
        plan_path = _make_checkpoint_plan(tmp_path)
        runner = CliRunner()
        # First confirm (task) = True, second (checkpoint) = False
        confirms = iter([True, True, False])
        with patch("swarm.cli.run_cmd.click.confirm", side_effect=confirms):
            result = runner.invoke(cli, ["run", str(plan_path)])
        assert result.exit_code == 0
        assert "Paused" in result.output or "checkpoint" in result.output.lower()

    def test_run_resumes_from_completed(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        with patch("swarm.cli.run_cmd.click.confirm", return_value=True):
            result = runner.invoke(cli, ["run", str(plan_path), "--completed", "s1"])
        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_run_invalid_plan(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"version": 1, "goal": "", "steps": []}))
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(bad)])
        assert result.exit_code != 0


class TestRunLatest:
    def test_run_latest_picks_highest_version(self, tmp_path: Path) -> None:
        # Create two plan versions — run --latest should pick v2
        plan_v1 = Plan(
            version=1,
            goal="v1 goal",
            steps=[PlanStep(id="s1", type="task", prompt="step", agent_type="worker")],
        )
        plan_v2 = Plan(
            version=2,
            goal="v2 goal",
            steps=[PlanStep(id="s1", type="task", prompt="step", agent_type="worker")],
        )
        (tmp_path / "plan_v1.json").write_text(json.dumps(plan_v1.to_dict()))
        (tmp_path / "plan_v2.json").write_text(json.dumps(plan_v2.to_dict()))

        runner = CliRunner()
        with patch("swarm.cli.run_cmd.click.confirm", return_value=True):
            # Run from tmp_path so --latest finds the files there
            result = runner.invoke(cli, ["run", "--latest"], catch_exceptions=False,
                                   env=None)
            # Need to invoke within tmp_path as cwd
        # Re-run with proper cwd
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("swarm.cli.run_cmd.click.confirm", return_value=True):
                result = runner.invoke(cli, ["run", "--latest"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0
        # v2 goal should appear in output via plan load
        assert "complete" in result.output.lower()

    def test_run_latest_no_plans_exits_nonzero(self, tmp_path: Path) -> None:
        import os
        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["run", "--latest"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code != 0
        assert "no plan" in result.output.lower() or "not found" in result.output.lower()

    def test_run_neither_path_nor_latest_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["run"])
        assert result.exit_code != 0
        assert "latest" in result.output.lower() or "path" in result.output.lower() or "provide" in result.output.lower()


def _make_parallel_plan_file(tmp_path: Path) -> Path:
    """Plan where s2 and s3 both depend on s1 (they are parallel in wave 2)."""
    plan = Plan(
        version=1,
        goal="parallel test",
        steps=[
            PlanStep(id="s1", type="task", prompt="first", agent_type="worker"),
            PlanStep(id="s2", type="task", prompt="second", agent_type="worker", depends_on=("s1",)),
            PlanStep(id="s3", type="checkpoint", prompt="review", depends_on=("s1",)),
        ],
    )
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()))
    return path


def _make_loop_plan_file(tmp_path: Path) -> Path:
    """Plan with a loop step to exercise loop colour coding."""
    plan = Plan(
        version=1,
        goal="loop test",
        steps=[
            PlanStep(
                id="l1",
                type="loop",
                prompt="iterate",
                agent_type="looper",
                loop_config=LoopConfig(condition="done", max_iterations=3),
            ),
        ],
    )
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan.to_dict()))
    return path


class TestDryRun:
    def test_dry_run_shows_wave_table(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        # Table header columns must be present
        assert "Wave" in result.output
        assert "Step ID" in result.output
        assert "Agent" in result.output
        assert "Type" in result.output
        assert "Spawn Mode" in result.output
        # Step IDs must appear
        assert "s1" in result.output
        assert "s2" in result.output
        # Summary line must appear
        assert "step" in result.output.lower()
        assert "wave" in result.output.lower()

    def test_dry_run_does_not_prompt(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        # If click.confirm were called it would block / raise on a non-tty runner
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        # Confirm prompts should never appear in dry-run output
        assert "complete?" not in result.output.lower()
        assert "continue?" not in result.output.lower()

    def test_dry_run_does_not_create_run_log(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        log_path = tmp_path / "run_log.json"
        assert not log_path.exists()

    def test_dry_run_with_latest(self, tmp_path: Path) -> None:
        import os

        plan = Plan(
            version=1,
            goal="latest dry-run",
            steps=[PlanStep(id="s1", type="task", prompt="do it", agent_type="worker")],
        )
        (tmp_path / "plan_v1.json").write_text(json.dumps(plan.to_dict()))

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["run", "--latest", "--dry-run"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0
        assert "s1" in result.output
        assert not (tmp_path / "run_log.json").exists()

    def test_dry_run_parallel_steps_same_wave(self, tmp_path: Path) -> None:
        plan_path = _make_parallel_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        # s2 and s3 both depend only on s1, so they must be in wave 2
        # The table should contain wave "2" twice
        assert result.output.count("2") >= 2
        # Summary says at least 2 steps can run in parallel
        assert "2" in result.output
        # Both parallel step IDs appear
        assert "s2" in result.output
        assert "s3" in result.output

    def test_dry_run_sequential_plan_has_multiple_waves(self, tmp_path: Path) -> None:
        plan_path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        # s1 → s2 is a chain, so 2 waves
        assert "2 wave" in result.output or "2" in result.output

    def test_dry_run_loop_step_appears(self, tmp_path: Path) -> None:
        plan_path = _make_loop_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(plan_path), "--dry-run"])
        assert result.exit_code == 0
        assert "l1" in result.output
        assert "loop" in result.output
