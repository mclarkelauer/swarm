"""Plan loading, validation, and saving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm.plan.models import Plan
from swarm.plan.versioning import next_version

_VALID_STEP_TYPES = {"task", "checkpoint", "loop"}


def load_plan(path: Path) -> Plan:
    """Load a plan from a JSON file.

    Args:
        path: Path to the plan JSON file.

    Returns:
        A ``Plan`` instance.
    """
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    return Plan.from_dict(data)


def validate_plan(plan: Plan) -> list[str]:
    """Validate a plan and return a list of error messages (empty if valid)."""
    errors: list[str] = []

    if not plan.goal:
        errors.append("Plan must have a goal")

    if not plan.steps:
        errors.append("Plan must have at least one step")

    step_ids = {s.id for s in plan.steps}

    for step in plan.steps:
        if not step.id:
            errors.append("Step is missing an id")

        if step.type not in _VALID_STEP_TYPES:
            errors.append(f"Step '{step.id}' has invalid type '{step.type}'")

        if step.type == "task" and not step.agent_type:
            errors.append(f"Task step '{step.id}' must specify an agent_type")

        if step.type == "loop" and step.loop_config is None:
            errors.append(f"Loop step '{step.id}' must have loop_config")

        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append(
                    f"Step '{step.id}' depends on unknown step '{dep}'"
                )

    return errors


def save_plan(plan: Plan, plans_dir: Path) -> Path:
    """Save a plan with auto-versioning.

    Args:
        plan: The plan to save.
        plans_dir: Directory to save plan versions in.

    Returns:
        Path to the saved plan file.
    """
    plans_dir.mkdir(parents=True, exist_ok=True)
    version = next_version(plans_dir)
    plan.version = version
    path = plans_dir / f"plan_v{version}.json"
    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return path
