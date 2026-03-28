"""Tests for swarm.cli.plan_cmd."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import save_plan


def _make_plan_file(tmp_path: Path) -> Path:
    plan = Plan(
        version=1,
        goal="test goal",
        steps=[
            PlanStep(id="s1", type="task", prompt="do stuff", agent_type="worker"),
            PlanStep(id="s2", type="task", prompt="next", agent_type="worker", depends_on=("s1",)),
        ],
    )
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    return path


class TestPlanValidate:
    def test_valid_plan(self, tmp_path: Path) -> None:
        path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "validate", str(path)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_invalid_plan(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('{"version": 1, "goal": "", "steps": []}', encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "validate", str(path)])
        assert result.exit_code != 0


class TestPlanList:
    def test_no_plans(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No plans" in result.output

    def test_lists_versions(self, tmp_path: Path) -> None:
        plan = Plan(
            version=1, goal="g",
            steps=[PlanStep(id="s1", type="task", prompt="p", agent_type="w")],
        )
        save_plan(plan, tmp_path)
        save_plan(plan, tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "plan_v1" in result.output
        assert "plan_v2" in result.output


class TestPlanShow:
    def test_shows_plan(self, tmp_path: Path) -> None:
        path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show", str(path)])
        assert result.exit_code == 0
        assert "test goal" in result.output
        assert "s1" in result.output
        assert "s2" in result.output


def _write_steps_file(tmp_path: Path) -> Path:
    steps = [
        {"id": "s1", "type": "task", "prompt": "first", "agent_type": "worker"},
        {"id": "s2", "type": "task", "prompt": "second", "agent_type": "worker", "depends_on": ["s1"]},
    ]
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(steps))
    return path


class TestPlanCreate:
    def test_create_saves_plan(self, tmp_path: Path) -> None:
        steps_file = _write_steps_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["plan", "create", "--goal", "Build it", "--steps-file", str(steps_file), "--dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Saved" in result.output
        assert (tmp_path / "plan_v1.json").exists()

    def test_create_dry_run(self, tmp_path: Path) -> None:
        steps_file = _write_steps_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["plan", "create", "--goal", "Build it", "--steps-file", str(steps_file), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_create_invalid_steps(self, tmp_path: Path) -> None:
        bad_steps = tmp_path / "bad.json"
        bad_steps.write_text(json.dumps([{"id": "s1", "type": "invalid", "prompt": "p"}]))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["plan", "create", "--goal", "Bad", "--steps-file", str(bad_steps)]
        )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_create_with_variables(self, tmp_path: Path) -> None:
        steps_file = _write_steps_file(tmp_path)
        vars_file = tmp_path / "vars.json"
        vars_file.write_text(json.dumps({"lang": "python"}))
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "plan", "create", "--goal", "Build it",
                "--steps-file", str(steps_file),
                "--variables", str(vars_file),
                "--dir", str(tmp_path),
            ],
        )
        assert result.exit_code == 0


class TestPlanResume:
    def test_resume_shows_next_steps(self, tmp_path: Path) -> None:
        path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "resume", str(path), "--completed", "s1"])
        assert result.exit_code == 0
        assert "s2" in result.output

    def test_resume_plan_complete(self, tmp_path: Path) -> None:
        path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "resume", str(path), "--completed", "s1,s2"])
        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_resume_no_completed(self, tmp_path: Path) -> None:
        path = _make_plan_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "resume", str(path)])
        assert result.exit_code == 0
        assert "s1" in result.output
