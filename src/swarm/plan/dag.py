"""DAG operations on execution plans."""

from __future__ import annotations

from swarm.plan.models import Plan, PlanStep


def detect_cycles(plan: Plan) -> None:
    """Raise ``ValueError`` if the plan's dependency graph contains a cycle."""
    step_map = {s.id: s for s in plan.steps}
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs(step_id: str) -> None:
        if step_id in in_stack:
            raise ValueError(f"Cycle detected involving step '{step_id}'")
        if step_id in visited:
            return
        in_stack.add(step_id)
        step = step_map.get(step_id)
        if step:
            for dep in step.depends_on:
                _dfs(dep)
        in_stack.remove(step_id)
        visited.add(step_id)

    for step in plan.steps:
        _dfs(step.id)


def topological_sort(plan: Plan) -> list[PlanStep]:
    """Return plan steps in topological order.

    Raises ``ValueError`` if the graph contains a cycle.
    """
    detect_cycles(plan)

    step_map = {s.id: s for s in plan.steps}
    visited: set[str] = set()
    order: list[PlanStep] = []

    def _visit(step_id: str) -> None:
        if step_id in visited:
            return
        visited.add(step_id)
        step = step_map[step_id]
        for dep in step.depends_on:
            _visit(dep)
        order.append(step)

    for step in plan.steps:
        _visit(step.id)

    return order


def get_ready_steps(plan: Plan, completed: set[str]) -> list[PlanStep]:
    """Return steps whose dependencies are all in the completed set.

    Only returns steps not already in ``completed``.
    """
    return [
        s
        for s in plan.steps
        if s.id not in completed and all(d in completed for d in s.depends_on)
    ]
