"""Plan template management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm.errors import PlanError
from swarm.plan.interpolation import safe_interpolate as _safe_interpolate
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import validate_plan

BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "builtin_templates"
USER_TEMPLATES_DIR = Path.home() / ".swarm" / "templates"

__all__ = [
    "BUILTIN_TEMPLATES_DIR",
    "USER_TEMPLATES_DIR",
    "_safe_interpolate",
    "instantiate_template",
    "list_template_params",
    "list_templates",
    "load_template",
    "load_templates",
]


def _load_template_from_path(path: Path) -> Plan:
    """Load a Plan from a JSON template file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Plan.from_dict(data)


def _load_raw_template(path: Path) -> dict[str, Any]:
    """Load raw JSON data from a template file."""
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def load_templates() -> dict[str, dict[str, Any]]:
    """Load all templates as raw dicts, keyed by name.

    User templates override builtin templates when names collide.

    Returns:
        Dict mapping template name to the raw JSON data (including
        ``parameter_definitions``, ``category``, and ``description``
        when present).
    """
    found: dict[str, dict[str, Any]] = {}

    for _source, directory in (("builtin", BUILTIN_TEMPLATES_DIR), ("user", USER_TEMPLATES_DIR)):
        if not directory.exists():
            continue
        for json_file in sorted(directory.glob("*.json")):
            name = json_file.stem
            try:
                raw = _load_raw_template(json_file)
                # Validate that it parses as a Plan (catches malformed templates).
                Plan.from_dict(raw)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue  # skip malformed templates silently
            raw["_source"] = _source
            found[name] = raw

    return found


def list_templates() -> list[dict[str, object]]:
    """Scan builtin and user template directories and return metadata.

    User templates override builtin templates when names collide.

    Returns:
        List of dicts with keys ``name``, ``goal``, ``step_count``,
        ``variables``, ``source`` (``"builtin"`` or ``"user"``),
        ``description``, ``category``, and ``parameter_definitions``.
    """
    found = load_templates()

    result: list[dict[str, object]] = []
    for name in sorted(found):
        raw = found[name]
        plan = Plan.from_dict(raw)
        result.append(
            {
                "name": name,
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "variables": list(plan.variables.keys()),
                "source": raw.get("_source", "builtin"),
                "description": raw.get("description", ""),
                "category": raw.get("category", ""),
                "parameter_definitions": raw.get("parameter_definitions", {}),
            }
        )
    return result


def list_template_params(name: str) -> dict[str, Any]:
    """Get parameter definitions for a template.

    Returns:
        Dict with template name, description, category, and parameter_definitions.
    """
    templates = load_templates()
    if name not in templates:
        return {"error": f"Template '{name}' not found"}

    tmpl = templates[name]
    return {
        "name": name,
        "description": tmpl.get("description", ""),
        "category": tmpl.get("category", ""),
        "parameter_definitions": tmpl.get("parameter_definitions", {}),
        "variables": tmpl.get("variables", {}),
    }


def load_template(name: str) -> Plan:
    """Load a template by name.

    Looks in the user directory first, then the builtin directory.

    Args:
        name: Template stem name (without ``.json`` extension).

    Returns:
        The loaded ``Plan`` instance.

    Raises:
        PlanError: If no template with the given name can be found.
    """
    for directory in (USER_TEMPLATES_DIR, BUILTIN_TEMPLATES_DIR):
        candidate = directory / f"{name}.json"
        if candidate.exists():
            return _load_template_from_path(candidate)
    raise PlanError(f"Template '{name}' not found")


def instantiate_template(name: str, variables: dict[str, str]) -> Plan:
    """Load a template and instantiate it with the supplied variables.

    Template-level default variables are merged with *variables*; caller
    values win on collision.  All ``{key}`` patterns in step prompts and
    ``agent_type`` fields are substituted; unknown placeholders are left
    intact.  The returned plan has ``version=1`` and passes validation.

    Args:
        name: Template name (without ``.json`` extension).
        variables: Variable overrides to apply on top of template defaults.

    Returns:
        An instantiated ``Plan`` ready for saving.

    Raises:
        PlanError: If the template is not found or the instantiated plan
            fails validation.
    """
    template = load_template(name)

    # Merge: template defaults first, caller overrides win.
    merged_vars: dict[str, str] = {**template.variables, **variables}

    # Interpolate each step's prompt and agent_type.
    new_steps: list[PlanStep] = []
    for step in template.steps:
        new_prompt = _safe_interpolate(step.prompt, merged_vars)
        new_agent_type = _safe_interpolate(step.agent_type, merged_vars)
        # PlanStep is frozen, so reconstruct with updated fields.
        new_step = PlanStep(
            id=step.id,
            type=step.type,
            prompt=new_prompt,
            agent_type=new_agent_type,
            depends_on=step.depends_on,
            loop_config=step.loop_config,
            checkpoint_config=step.checkpoint_config,
            fan_out_config=step.fan_out_config,
            output_artifact=step.output_artifact,
            required_inputs=step.required_inputs,
            on_failure=step.on_failure,
            spawn_mode=step.spawn_mode,
            condition=step.condition,
            required_tools=step.required_tools,
            critic_agent=step.critic_agent,
            max_critic_iterations=step.max_critic_iterations,
        )
        new_steps.append(new_step)

    # Interpolate the goal as well.
    new_goal = _safe_interpolate(template.goal, merged_vars)

    plan = Plan(
        version=1,
        goal=new_goal,
        steps=new_steps,
        variables=merged_vars,
    )

    errors = validate_plan(plan)
    if errors:
        raise PlanError(f"Instantiated template '{name}' failed validation: {'; '.join(errors)}")

    return plan
