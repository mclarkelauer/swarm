"""Tests for swarm.plan.models: Plan, PlanStep, LoopConfig, CheckpointConfig."""

from __future__ import annotations

from swarm.plan.models import CheckpointConfig, LoopConfig, Plan, PlanStep


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
        assert lc.max_iterations == 100_000


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
