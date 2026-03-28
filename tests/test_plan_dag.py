"""Tests for swarm.plan.dag: detect_cycles, topological_sort, get_ready_steps."""

from __future__ import annotations

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
