"""MCP tools for the plan system."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.plan.dag import detect_cycles, get_ready_steps
from swarm.plan.discovery import find_plans_dir
from swarm.plan.models import Plan
from swarm.plan.parser import load_plan, save_plan, validate_plan
from swarm.plan.versioning import list_versions


def _resolve_plans_dir(plans_dir: str) -> Path:
    """Resolve the plans directory from an explicit path or the configured default."""
    if plans_dir:
        return Path(plans_dir)
    if state.plans_dir:
        return Path(state.plans_dir)
    return find_plans_dir() or Path.cwd()


@mcp.tool()
def plan_create(
    goal: str,
    steps_json: str,
    variables_json: str = "{}",
    plans_dir: str = "",
) -> str:
    """Create, validate, and save a new plan.

    Args:
        goal: The plan's goal description.
        steps_json: JSON array of step objects.  Each step needs ``id``,
            ``type``, ``prompt``.  Task steps also need ``agent_type``.
            Optional: ``depends_on`` (array of step IDs),
            ``loop_config`` (``{condition, max_iterations}``),
            ``checkpoint_config`` (``{message}``).
        variables_json: JSON object of plan variables for prompt interpolation.
        plans_dir: Directory to save the plan in (default: configured plans_dir).

    Returns:
        JSON ``{path, version, errors}`` — errors is an empty array if valid.
    """
    steps = json.loads(steps_json)
    variables = json.loads(variables_json)

    plan_data = {
        "version": 1,
        "goal": goal,
        "steps": steps,
        "variables": variables,
    }
    plan = Plan.from_dict(plan_data)

    errors = validate_plan(plan)
    if not errors:
        try:
            detect_cycles(plan)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return json.dumps({"path": None, "version": None, "errors": errors})

    target = _resolve_plans_dir(plans_dir)
    saved_path = save_plan(plan, target)
    return json.dumps({
        "path": str(saved_path),
        "version": plan.version,
        "errors": [],
    })


@mcp.tool()
def plan_validate(plan_json: str) -> str:
    """Validate a plan without saving it.

    Args:
        plan_json: Full plan JSON string with version, goal, steps.

    Returns:
        JSON ``{valid, errors}``.
    """
    data = json.loads(plan_json)
    plan = Plan.from_dict(data)
    errors = validate_plan(plan)
    if not errors:
        try:
            detect_cycles(plan)
        except ValueError as exc:
            errors.append(str(exc))
    return json.dumps({"valid": len(errors) == 0, "errors": errors})


@mcp.tool()
def plan_load(path: str) -> str:
    """Load a plan from a JSON file on disk.

    Args:
        path: Path to the plan JSON file.

    Returns:
        JSON string of the loaded plan.
    """
    plan = load_plan(Path(path))
    return json.dumps(plan.to_dict())


@mcp.tool()
def plan_list(plans_dir: str = "") -> str:
    """List all plan versions in a directory.

    Args:
        plans_dir: Directory to scan (default: configured plans_dir).

    Returns:
        JSON array of ``{version, path}`` objects.
    """
    target = _resolve_plans_dir(plans_dir)
    versions = list_versions(target)
    result = [
        {"version": v, "path": str(target / f"plan_v{v}.json")}
        for v in versions
    ]
    return json.dumps(result)


@mcp.tool()
def plan_get_ready_steps(plan_json: str, completed_json: str = "[]") -> str:
    """Get steps that are ready to execute (all dependencies met).

    Args:
        plan_json: Full plan JSON string.
        completed_json: JSON array of completed step ID strings.

    Returns:
        JSON array of step objects ready for execution.
    """
    data = json.loads(plan_json)
    plan = Plan.from_dict(data)
    completed: set[str] = set(json.loads(completed_json))
    ready = get_ready_steps(plan, completed)
    return json.dumps([s.to_dict() for s in ready])


@mcp.tool()
def plan_get_step(plan_json: str, step_id: str) -> str:
    """Get details of a single step from a plan.

    Args:
        plan_json: Full plan JSON string.
        step_id: The step ID to retrieve.

    Returns:
        JSON of the step, or error if not found.
    """
    data = json.loads(plan_json)
    plan = Plan.from_dict(data)
    for step in plan.steps:
        if step.id == step_id:
            return json.dumps(step.to_dict())
    return json.dumps({"error": f"Step '{step_id}' not found"})
