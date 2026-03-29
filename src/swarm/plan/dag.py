"""DAG operations on execution plans."""

from __future__ import annotations

from pathlib import Path

from swarm.plan.conditions import evaluate_condition
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


def get_ready_steps(
    plan: Plan,
    completed: set[str],
    artifacts_dir: Path | None = None,
    step_outcomes: dict[str, str] | None = None,
) -> list[PlanStep]:
    """Return steps whose dependencies are all in the completed set.

    Only returns steps not already in ``completed``.

    Args:
        plan: The execution plan.
        completed: Set of step IDs that have already completed.
        artifacts_dir: When provided, steps with ``required_inputs`` are only
            returned if every listed path exists under this directory.  When
            ``None``, the file-existence check is skipped entirely (backward
            compatible behaviour).
        step_outcomes: Optional mapping of step ID to outcome string (e.g.
            ``"failed"``).  Passed through to ``evaluate_condition`` for
            ``step_failed:`` expressions.
    """
    ready: list[PlanStep] = []
    for s in plan.steps:
        if s.id in completed:
            continue
        if not all(d in completed for d in s.depends_on):
            continue
        if (
            artifacts_dir is not None
            and s.required_inputs
            and not all((artifacts_dir / inp).exists() for inp in s.required_inputs)
        ):
            continue
        if not evaluate_condition(
            s.condition,
            completed,
            step_outcomes=step_outcomes,
            artifacts_dir=artifacts_dir,
        ):
            continue
        ready.append(s)
    return ready
