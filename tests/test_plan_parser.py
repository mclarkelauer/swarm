"""Tests for swarm.plan.parser: load_plan, validate_plan, save_plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.plan.models import ConditionalAction, DecisionConfig, Plan, PlanStep
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


class TestValidatePlanNewFields:
    def test_validate_invalid_on_failure(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="do work",
                    agent_type="worker",
                    on_failure="crash",  # invalid value
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("on_failure" in e and "crash" in e for e in errors)

    def test_validate_invalid_spawn_mode(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="do work",
                    agent_type="worker",
                    spawn_mode="detached",  # invalid value
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("spawn_mode" in e and "detached" in e for e in errors)

    def test_validate_empty_required_input(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="do work",
                    agent_type="worker",
                    required_inputs=("valid.md", ""),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("empty" in e.lower() and "required_inputs" in e for e in errors)

    def test_validate_valid_on_failure_values(self) -> None:
        for value in ("stop", "skip", "retry"):
            plan = Plan(
                version=1,
                goal="test goal",
                steps=[
                    PlanStep(
                        id="s1",
                        type="task",
                        prompt="do work",
                        agent_type="worker",
                        on_failure=value,
                    ),
                ],
            )
            errors = validate_plan(plan)
            on_failure_errors = [e for e in errors if "on_failure" in e]
            assert on_failure_errors == [], f"on_failure='{value}' should be valid but got: {on_failure_errors}"

    def test_validate_valid_spawn_mode_values(self) -> None:
        for value in ("foreground", "background"):
            plan = Plan(
                version=1,
                goal="test goal",
                steps=[
                    PlanStep(
                        id="s1",
                        type="task",
                        prompt="do work",
                        agent_type="worker",
                        spawn_mode=value,
                    ),
                ],
            )
            errors = validate_plan(plan)
            spawn_errors = [e for e in errors if "spawn_mode" in e]
            assert spawn_errors == [], f"spawn_mode='{value}' should be valid but got: {spawn_errors}"


class TestValidatePlanConditions:
    def test_invalid_condition_produces_error(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="do work",
                    agent_type="worker",
                    condition="unknown_format_xyz",
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("s1" in e for e in errors)
        assert len(errors) > 0

    def test_known_prefix_with_empty_value_produces_error(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="do work",
                    agent_type="worker",
                    condition="artifact_exists:",
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("s1" in e for e in errors)

    def test_valid_conditions_produce_no_errors(self) -> None:
        valid_conditions = [
            "",
            "always",
            "never",
            "artifact_exists:output.md",
            "step_completed:s0",
            "step_failed:s0",
        ]
        for cond in valid_conditions:
            plan = Plan(
                version=1,
                goal="test goal",
                steps=[
                    PlanStep(
                        id="s1",
                        type="task",
                        prompt="do work",
                        agent_type="worker",
                        condition=cond,
                    ),
                ],
            )
            errors = validate_plan(plan)
            condition_errors = [e for e in errors if "condition" in e.lower() or "Unknown" in e]
            assert condition_errors == [], (
                f"condition='{cond}' should be valid but got errors: {condition_errors}"
            )


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


class TestValidateDecisionStep:
    def test_valid_decision_step(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(id="build", type="task", prompt="build", agent_type="builder"),
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    depends_on=("build",),
                    decision_config=DecisionConfig(
                        actions=(
                            ConditionalAction(
                                condition="step_completed:build",
                                activate_steps=("build",),
                            ),
                        ),
                    ),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert errors == []

    def test_decision_missing_config(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(id="decide", type="decision", prompt="branch"),
            ],
        )
        errors = validate_plan(plan)
        assert any("decision_config" in e for e in errors)

    def test_decision_empty_actions(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    decision_config=DecisionConfig(actions=()),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("at least one action" in e for e in errors)

    def test_decision_invalid_condition_in_action(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    decision_config=DecisionConfig(
                        actions=(
                            ConditionalAction(
                                condition="unknown_format_xyz",
                            ),
                        ),
                    ),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("action 0" in e for e in errors)

    def test_decision_unknown_activate_step(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    decision_config=DecisionConfig(
                        actions=(
                            ConditionalAction(
                                condition="always",
                                activate_steps=("nonexistent",),
                            ),
                        ),
                    ),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("activate_steps" in e and "nonexistent" in e for e in errors)

    def test_decision_unknown_skip_step(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    decision_config=DecisionConfig(
                        actions=(
                            ConditionalAction(
                                condition="always",
                                skip_steps=("missing",),
                            ),
                        ),
                    ),
                ),
            ],
        )
        errors = validate_plan(plan)
        assert any("skip_steps" in e and "missing" in e for e in errors)

    def test_decision_step_does_not_require_agent_type(self) -> None:
        plan = Plan(
            version=1,
            goal="test",
            steps=[
                PlanStep(
                    id="decide",
                    type="decision",
                    prompt="branch",
                    decision_config=DecisionConfig(
                        actions=(
                            ConditionalAction(condition="always"),
                        ),
                    ),
                ),
            ],
        )
        errors = validate_plan(plan)
        # No agent_type errors for decision steps
        agent_errors = [e for e in errors if "agent_type" in e]
        assert agent_errors == []
