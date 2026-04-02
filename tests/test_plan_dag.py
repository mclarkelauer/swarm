"""Tests for swarm.plan.dag: detect_cycles, topological_sort, get_ready_steps."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.plan.dag import detect_cycles, get_ready_steps, topological_sort
from swarm.plan.models import Plan, PlanStep


def _plan(*steps: PlanStep) -> Plan:
    return Plan(version=1, goal="test", steps=list(steps))


class TestDetectCycles:
    def test_linear_chain_no_cycle(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("b",)),
        )
        detect_cycles(plan)  # should not raise

    def test_cycle_raises(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", depends_on=("b",)),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        with pytest.raises(ValueError, match="Cycle"):
            detect_cycles(plan)

    def test_self_cycle_raises(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        with pytest.raises(ValueError, match="Cycle"):
            detect_cycles(plan)

    def test_diamond_no_cycle(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="d", type="task", prompt="p", agent_type="w", depends_on=("b", "c")),
        )
        detect_cycles(plan)  # should not raise

    def test_no_deps_no_cycle(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w"),
        )
        detect_cycles(plan)


class TestTopologicalSort:
    def test_linear_order(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("b",)),
        )
        order = topological_sort(plan)
        ids = [s.id for s in order]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_diamond_order(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="d", type="task", prompt="p", agent_type="w", depends_on=("b", "c")),
        )
        order = topological_sort(plan)
        ids = [s.id for s in order]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_raises_on_cycle(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", depends_on=("b",)),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        with pytest.raises(ValueError, match="Cycle"):
            topological_sort(plan)

    def test_independent_steps(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w"),
        )
        order = topological_sort(plan)
        assert len(order) == 2


class TestGetReadySteps:
    def test_initial_ready(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        ready = get_ready_steps(plan, set())
        assert [s.id for s in ready] == ["a"]

    def test_after_first_complete(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        ready = get_ready_steps(plan, {"a"})
        ids = {s.id for s in ready}
        assert ids == {"b", "c"}

    def test_diamond_progression(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="d", type="task", prompt="p", agent_type="w", depends_on=("b", "c")),
        )
        # Only a is ready initially
        assert [s.id for s in get_ready_steps(plan, set())] == ["a"]
        # After a, b and c are ready
        assert {s.id for s in get_ready_steps(plan, {"a"})} == {"b", "c"}
        # After a+b, only c (d still needs c)
        assert {s.id for s in get_ready_steps(plan, {"a", "b"})} == {"c"}
        # After a+b+c, d is ready
        assert {s.id for s in get_ready_steps(plan, {"a", "b", "c"})} == {"d"}
        # After all complete, nothing ready
        assert get_ready_steps(plan, {"a", "b", "c", "d"}) == []

    def test_all_independent(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w"),
            PlanStep(id="c", type="task", prompt="p", agent_type="w"),
        )
        ready = get_ready_steps(plan, set())
        assert {s.id for s in ready} == {"a", "b", "c"}


class TestGetReadyStepsWithConditions:
    def test_condition_never_step_not_ready(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
        )
        ready = get_ready_steps(plan, set())
        assert ready == []

    def test_condition_always_step_is_ready(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="always"),
        )
        ready = get_ready_steps(plan, set())
        assert [s.id for s in ready] == ["a"]

    def test_condition_step_completed_satisfied(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(
                id="b",
                type="task",
                prompt="p",
                agent_type="w",
                condition="step_completed:a",
            ),
        )
        ready = get_ready_steps(plan, {"a"})
        assert any(s.id == "b" for s in ready)

    def test_condition_step_completed_not_satisfied(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(
                id="b",
                type="task",
                prompt="p",
                agent_type="w",
                condition="step_completed:a",
            ),
        )
        # a is not completed yet — b's condition blocks it
        ready = get_ready_steps(plan, set())
        ready_ids = {s.id for s in ready}
        assert "b" not in ready_ids

    def test_step_outcomes_parameter_passed_through(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(
                id="b",
                type="task",
                prompt="p",
                agent_type="w",
                condition="step_failed:a",
            ),
        )
        # a is in completed and also marked failed in outcomes
        outcomes = {"a": "failed"}
        ready = get_ready_steps(plan, {"a"}, step_outcomes=outcomes)
        assert any(s.id == "b" for s in ready)

    def test_step_outcomes_none_blocks_step_failed_condition(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(
                id="b",
                type="task",
                prompt="p",
                agent_type="w",
                condition="step_failed:a",
            ),
        )
        # Without outcomes, step_failed evaluates to False
        ready = get_ready_steps(plan, {"a"}, step_outcomes=None)
        ready_ids = {s.id for s in ready}
        assert "b" not in ready_ids

    def test_condition_never_does_not_block_other_steps(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w"),
        )
        ready = get_ready_steps(plan, set())
        ready_ids = {s.id for s in ready}
        assert "a" not in ready_ids
        assert "b" in ready_ids


class TestGetReadyStepsWithArtifactsDir:
    def test_get_ready_steps_with_artifacts_dir_satisfied(self, tmp_path: Path) -> None:
        (tmp_path / "input.md").write_text("content", encoding="utf-8")
        plan = _plan(
            PlanStep(
                id="a",
                type="task",
                prompt="p",
                agent_type="w",
                required_inputs=("input.md",),
            ),
        )
        ready = get_ready_steps(plan, set(), artifacts_dir=tmp_path)
        assert [s.id for s in ready] == ["a"]

    def test_get_ready_steps_with_artifacts_dir_missing(self, tmp_path: Path) -> None:
        # "input.md" is NOT created in tmp_path
        plan = _plan(
            PlanStep(
                id="a",
                type="task",
                prompt="p",
                agent_type="w",
                required_inputs=("input.md",),
            ),
        )
        ready = get_ready_steps(plan, set(), artifacts_dir=tmp_path)
        assert ready == []

    def test_get_ready_steps_without_artifacts_dir_skips_check(self, tmp_path: Path) -> None:
        # File does not exist, but no artifacts_dir is provided — step should be ready
        plan = _plan(
            PlanStep(
                id="a",
                type="task",
                prompt="p",
                agent_type="w",
                required_inputs=("nonexistent.md",),
            ),
        )
        ready = get_ready_steps(plan, set(), artifacts_dir=None)
        assert [s.id for s in ready] == ["a"]

    def test_get_ready_steps_no_required_inputs_with_artifacts_dir(self, tmp_path: Path) -> None:
        # Step has no required_inputs; artifacts_dir provided but irrelevant
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
        )
        ready = get_ready_steps(plan, set(), artifacts_dir=tmp_path)
        assert [s.id for s in ready] == ["a"]


class TestGetReadyStepsWithDecisionOverrides:
    def test_decision_override_activates_never_step(self) -> None:
        """A step with condition='never' becomes ready when overridden by a decision."""
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
        )
        # Without override, not ready
        assert get_ready_steps(plan, set()) == []
        # With override, ready
        ready = get_ready_steps(plan, set(), decision_overrides={"a": ""})
        assert [s.id for s in ready] == ["a"]

    def test_decision_override_does_not_affect_unmentioned_steps(self) -> None:
        """Steps not in overrides still use their own condition."""
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", condition="never"),
        )
        ready = get_ready_steps(plan, set(), decision_overrides={"a": ""})
        assert [s.id for s in ready] == ["a"]

    def test_decision_override_empty_dict_no_effect(self) -> None:
        """Empty overrides dict has no effect."""
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
        )
        ready = get_ready_steps(plan, set(), decision_overrides={})
        assert ready == []

    def test_decision_override_none_no_effect(self) -> None:
        """None overrides has no effect (backward compat)."""
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w", condition="never"),
        )
        ready = get_ready_steps(plan, set(), decision_overrides=None)
        assert ready == []
