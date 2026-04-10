"""Tests for swarm.plan.models: Plan, PlanStep, LoopConfig, CheckpointConfig, DecisionConfig."""

from __future__ import annotations

from swarm.plan.models import (
    CheckpointConfig,
    ConditionalAction,
    DecisionConfig,
    LoopConfig,
    Plan,
    PlanStep,
)


class TestPlanStepConstruction:
    def test_basic_task_step(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="Do work", agent_type="worker")
        assert step.id == "s1"
        assert step.type == "task"
        assert step.depends_on == ()

    def test_step_with_dependencies(self) -> None:
        step = PlanStep(id="s2", type="task", prompt="p", depends_on=("s1",))
        assert step.depends_on == ("s1",)

    def test_loop_step(self) -> None:
        step = PlanStep(
            id="loop",
            type="loop",
            prompt="iterate",
            loop_config=LoopConfig(condition="done", max_iterations=10),
        )
        assert step.loop_config is not None
        assert step.loop_config.condition == "done"
        assert step.loop_config.max_iterations == 10

    def test_checkpoint_step(self) -> None:
        step = PlanStep(
            id="cp",
            type="checkpoint",
            prompt="review",
            checkpoint_config=CheckpointConfig(message="Ready?"),
        )
        assert step.checkpoint_config is not None
        assert step.checkpoint_config.message == "Ready?"


class TestLoopConfigDefaults:
    def test_defaults(self) -> None:
        lc = LoopConfig()
        assert lc.condition == ""
        assert lc.max_iterations == 10


class TestCheckpointConfigDefaults:
    def test_defaults(self) -> None:
        cc = CheckpointConfig()
        assert cc.message == ""


class TestPlanConstruction:
    def test_basic_plan(self) -> None:
        plan = Plan(
            version=1,
            goal="test goal",
            steps=[PlanStep(id="s1", type="task", prompt="p", agent_type="w")],
        )
        assert plan.version == 1
        assert plan.goal == "test goal"
        assert len(plan.steps) == 1

    def test_plan_with_variables(self) -> None:
        plan = Plan(version=1, goal="g", steps=[], variables={"key": "value"})
        assert plan.variables["key"] == "value"

    def test_plan_default_variables(self) -> None:
        plan = Plan(version=1, goal="g", steps=[])
        assert plan.variables == {}


class TestPlanStepNewFields:
    def test_plan_step_new_fields_roundtrip(self) -> None:
        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            output_artifact="out.md",
            required_inputs=("in1.md", "in2.md"),
            on_failure="retry",
            spawn_mode="background",
        )
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.output_artifact == "out.md"
        assert restored.required_inputs == ("in1.md", "in2.md")
        assert restored.on_failure == "retry"
        assert restored.spawn_mode == "background"

    def test_plan_step_defaults(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="do work")
        assert step.output_artifact == ""
        assert step.required_inputs == ()
        assert step.on_failure == "stop"
        assert step.spawn_mode == "foreground"

    def test_plan_step_sparse_serialization(self) -> None:
        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            # All new fields at their defaults
            output_artifact="",
            required_inputs=(),
            on_failure="stop",
            spawn_mode="foreground",
        )
        d = step.to_dict()
        assert "output_artifact" not in d
        assert "required_inputs" not in d
        assert "on_failure" not in d
        assert "spawn_mode" not in d

    def test_plan_step_from_dict_backward_compat(self) -> None:
        # A dict that represents an old-format step (missing all new fields)
        old_dict = {
            "id": "legacy-step",
            "type": "task",
            "prompt": "do legacy work",
            "agent_type": "worker",
        }
        step = PlanStep.from_dict(old_dict)
        assert step.output_artifact == ""
        assert step.required_inputs == ()
        assert step.on_failure == "stop"
        assert step.spawn_mode == "foreground"


class TestPlanStepConditionField:
    def test_condition_roundtrip(self) -> None:
        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            condition="step_completed:s0",
        )
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.condition == "step_completed:s0"

    def test_condition_sparse_serialization_empty_omitted(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w", condition="")
        d = step.to_dict()
        assert "condition" not in d

    def test_condition_sparse_serialization_nonempty_included(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w", condition="never")
        d = step.to_dict()
        assert d["condition"] == "never"

    def test_condition_from_dict_backward_compat_missing_defaults_to_empty(self) -> None:
        old_dict = {
            "id": "legacy-step",
            "type": "task",
            "prompt": "do legacy work",
            "agent_type": "worker",
        }
        step = PlanStep.from_dict(old_dict)
        assert step.condition == ""

    def test_condition_default_is_empty_string(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        assert step.condition == ""


class TestJsonRoundTrip:
    def test_plan_step_round_trip(self) -> None:
        step = PlanStep(
            id="s1",
            type="loop",
            prompt="iterate",
            agent_type="worker",
            depends_on=("s0",),
            loop_config=LoopConfig(condition="done", max_iterations=5),
        )
        d = step.to_dict()
        restored = PlanStep.from_dict(d)
        assert restored.id == step.id
        assert restored.type == step.type
        assert restored.depends_on == step.depends_on
        assert restored.loop_config is not None
        assert restored.loop_config.condition == "done"

    def test_plan_round_trip(self) -> None:
        plan = Plan(
            version=2,
            goal="build it",
            steps=[
                PlanStep(id="a", type="task", prompt="first", agent_type="dev"),
                PlanStep(
                    id="b",
                    type="checkpoint",
                    prompt="review",
                    depends_on=("a",),
                    checkpoint_config=CheckpointConfig(message="ok?"),
                ),
            ],
            variables={"repo": "swarm"},
        )
        d = plan.to_dict()
        restored = Plan.from_dict(d)
        assert restored.version == 2
        assert restored.goal == "build it"
        assert len(restored.steps) == 2
        assert restored.steps[1].checkpoint_config is not None
        assert restored.variables["repo"] == "swarm"

    def test_loop_config_round_trip(self) -> None:
        lc = LoopConfig(condition="items done", max_iterations=50)
        assert LoopConfig.from_dict(lc.to_dict()) == lc

    def test_checkpoint_config_round_trip(self) -> None:
        cc = CheckpointConfig(message="Review?")
        assert CheckpointConfig.from_dict(cc.to_dict()) == cc


# ---------------------------------------------------------------------------
# ConditionalAction
# ---------------------------------------------------------------------------


class TestConditionalAction:
    def test_defaults(self) -> None:
        ca = ConditionalAction(condition="step_completed:s1")
        assert ca.activate_steps == ()
        assert ca.skip_steps == ()

    def test_round_trip_full(self) -> None:
        ca = ConditionalAction(
            condition="output_contains:build:ERROR",
            activate_steps=("fix-deps",),
            skip_steps=("test", "deploy"),
        )
        restored = ConditionalAction.from_dict(ca.to_dict())
        assert restored == ca

    def test_sparse_serialization_empty_tuples(self) -> None:
        ca = ConditionalAction(condition="always")
        d = ca.to_dict()
        assert "activate_steps" not in d
        assert "skip_steps" not in d
        assert d["condition"] == "always"

    def test_from_dict_backward_compat(self) -> None:
        d = {"condition": "step_completed:s1"}
        ca = ConditionalAction.from_dict(d)
        assert ca.activate_steps == ()
        assert ca.skip_steps == ()


# ---------------------------------------------------------------------------
# DecisionConfig
# ---------------------------------------------------------------------------


class TestDecisionConfig:
    def test_empty_actions(self) -> None:
        dc = DecisionConfig()
        assert dc.actions == ()

    def test_round_trip(self) -> None:
        dc = DecisionConfig(
            actions=(
                ConditionalAction(
                    condition="output_contains:build:ERROR.*dep",
                    activate_steps=("fix-deps",),
                    skip_steps=("test",),
                ),
                ConditionalAction(
                    condition="step_completed:build",
                    activate_steps=("test",),
                ),
            ),
        )
        restored = DecisionConfig.from_dict(dc.to_dict())
        assert restored == dc
        assert len(restored.actions) == 2

    def test_from_dict_missing_actions(self) -> None:
        dc = DecisionConfig.from_dict({})
        assert dc.actions == ()


# ---------------------------------------------------------------------------
# PlanStep with decision_config
# ---------------------------------------------------------------------------


class TestPlanStepDecisionConfig:
    def test_decision_config_default_is_none(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        assert step.decision_config is None

    def test_decision_config_round_trip(self) -> None:
        dc = DecisionConfig(
            actions=(
                ConditionalAction(
                    condition="step_completed:build",
                    activate_steps=("test",),
                ),
            ),
        )
        step = PlanStep(
            id="decide",
            type="decision",
            prompt="Branch based on build",
            decision_config=dc,
        )
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.decision_config is not None
        assert len(restored.decision_config.actions) == 1
        assert restored.decision_config.actions[0].activate_steps == ("test",)

    def test_decision_config_sparse_serialization(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w")
        d = step.to_dict()
        assert "decision_config" not in d

    def test_from_dict_backward_compat_no_decision_config(self) -> None:
        old_dict = {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"}
        step = PlanStep.from_dict(old_dict)
        assert step.decision_config is None


# ---------------------------------------------------------------------------
# Plan max_replans
# ---------------------------------------------------------------------------


class TestPlanMaxReplans:
    def test_default_max_replans(self) -> None:
        plan = Plan(version=1, goal="g", steps=[])
        assert plan.max_replans == 5

    def test_custom_max_replans(self) -> None:
        plan = Plan(version=1, goal="g", steps=[], max_replans=10)
        assert plan.max_replans == 10

    def test_max_replans_round_trip_non_default(self) -> None:
        plan = Plan(version=1, goal="g", steps=[], max_replans=3)
        d = plan.to_dict()
        assert d["max_replans"] == 3
        restored = Plan.from_dict(d)
        assert restored.max_replans == 3

    def test_max_replans_sparse_serialization_default_omitted(self) -> None:
        plan = Plan(version=1, goal="g", steps=[])
        d = plan.to_dict()
        assert "max_replans" not in d

    def test_from_dict_backward_compat_missing_defaults_to_five(self) -> None:
        d = {"version": 1, "goal": "g", "steps": []}
        plan = Plan.from_dict(d)
        assert plan.max_replans == 5


class TestPlanStepTimeout:
    """Tests for per-step timeout field."""

    def test_timeout_defaults_to_zero(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        assert step.timeout == 0

    def test_timeout_zero_not_emitted_in_to_dict(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", timeout=0)
        d = step.to_dict()
        assert "timeout" not in d

    def test_timeout_positive_emitted_in_to_dict(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", timeout=300)
        d = step.to_dict()
        assert d["timeout"] == 300

    def test_timeout_roundtrip(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", timeout=600)
        d = step.to_dict()
        restored = PlanStep.from_dict(d)
        assert restored.timeout == 600

    def test_from_dict_without_timeout_defaults_to_zero(self) -> None:
        d = {"id": "s1", "type": "task", "prompt": "p"}
        step = PlanStep.from_dict(d)
        assert step.timeout == 0
