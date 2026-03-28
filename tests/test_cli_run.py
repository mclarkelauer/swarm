"""Tests for the ``swarm run`` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.plan.models import Plan, PlanStep
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
