"""Tests for swarm.plan.parser: load_plan, validate_plan, save_plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import load_plan, save_plan, validate_plan


@pytest.fixture()
def sample_plan() -> Plan:
    return Plan(
        version=1,
        goal="test goal",
        steps=[
            PlanStep(id="s1", type="task", prompt="do it", agent_type="worker"),
            PlanStep(id="s2", type="task", prompt="next", agent_type="worker", depends_on=("s1",)),
        ],
    )


class TestLoadPlan:
    def test_loads_from_file(self, tmp_path: Path, sample_plan: Plan) -> None:
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(sample_plan.to_dict()), encoding="utf-8")
        loaded = load_plan(path)
        assert loaded.goal == "test goal"
        assert len(loaded.steps) == 2

    def test_loads_with_loop_config(self, tmp_path: Path) -> None:
        data = {
            "version": 1,
            "goal": "g",
            "steps": [
                {
                    "id": "loop1",
                    "type": "loop",
                    "prompt": "iterate",
                    "agent_type": "worker",
                    "loop_config": {"condition": "done", "max_iterations": 10},
                }
            ],
        }
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        plan = load_plan(path)
        assert plan.steps[0].loop_config is not None
        assert plan.steps[0].loop_config.max_iterations == 10


class TestValidatePlan:
    def test_valid_plan(self, sample_plan: Plan) -> None:
        assert validate_plan(sample_plan) == []

    def test_missing_goal(self) -> None:
        plan = Plan(
            version=1,
            goal="",
            steps=[PlanStep(id="s1", type="task", prompt="p", agent_type="w")],
        )
        errors = validate_plan(plan)
        assert any("goal" in e for e in errors)

    def test_no_steps(self) -> None:
        plan = Plan(version=1, goal="g", steps=[])
        errors = validate_plan(plan)
        assert any("step" in e.lower() for e in errors)

    def test_invalid_step_type(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[PlanStep(id="s1", type="invalid_type", prompt="p")],
        )
        errors = validate_plan(plan)
        assert any("invalid type" in e for e in errors)

    def test_task_without_agent_type(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[PlanStep(id="s1", type="task", prompt="p")],
        )
        errors = validate_plan(plan)
        assert any("agent_type" in e for e in errors)

    def test_loop_without_config(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[PlanStep(id="s1", type="loop", prompt="p", agent_type="w")],
        )
        errors = validate_plan(plan)
        assert any("loop_config" in e for e in errors)

    def test_unknown_dependency(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[
                PlanStep(id="s1", type="task", prompt="p", agent_type="w", depends_on=("missing",)),
            ],
        )
        errors = validate_plan(plan)
        assert any("unknown step" in e for e in errors)

    def test_checkpoint_is_valid_without_agent_type(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[PlanStep(id="cp", type="checkpoint", prompt="review")],
        )
        errors = validate_plan(plan)
        assert errors == []


class TestSavePlan:
    def test_saves_with_version(self, tmp_path: Path, sample_plan: Plan) -> None:
        path = save_plan(sample_plan, tmp_path)
        assert path.name == "plan_v1.json"
        assert path.exists()

    def test_auto_increments_version(self, tmp_path: Path, sample_plan: Plan) -> None:
        save_plan(sample_plan, tmp_path)
        path2 = save_plan(sample_plan, tmp_path)
        assert path2.name == "plan_v2.json"

    def test_saved_plan_is_loadable(self, tmp_path: Path, sample_plan: Plan) -> None:
        path = save_plan(sample_plan, tmp_path)
        loaded = load_plan(path)
        assert loaded.goal == sample_plan.goal
        assert len(loaded.steps) == len(sample_plan.steps)
