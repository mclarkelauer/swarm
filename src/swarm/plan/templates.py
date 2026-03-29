"""Plan template management."""

from __future__ import annotations

import json
import re
from pathlib import Path

from swarm.errors import PlanError
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import validate_plan

BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "builtin_templates"
USER_TEMPLATES_DIR = Path.home() / ".swarm" / "templates"


def _safe_interpolate(template: str, variables: dict[str, str]) -> str:
    """Interpolate ``{key}`` placeholders in *template* from *variables*.

    Keys absent from *variables* are left as-is (no KeyError).
    """

    def _replacer(match: re.Match[str]) -> str:
        return variables.get(match.group(1), match.group(0))

    return re.sub(r"\{(\w+)\}", _replacer, template)


def _load_template_from_path(path: Path) -> Plan:
    """Load a Plan from a JSON template file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Plan.from_dict(data)


def list_templates() -> list[dict[str, object]]:
    """Scan builtin and user template directories and return metadata.

    User templates override builtin templates when names collide.

    Returns:
        List of dicts with keys ``name``, ``goal``, ``step_count``,
        ``variables``, and ``source`` (``"builtin"`` or ``"user"``).
    """
    # Collect builtins first, then overlay user templates (user wins on collision).
    found: dict[str, tuple[Plan, str]] = {}  # name -> (plan, source)

    for source, directory in (("builtin", BUILTIN_TEMPLATES_DIR), ("user", USER_TEMPLATES_DIR)):
        if not directory.exists():
            continue
        for json_file in sorted(directory.glob("*.json")):
            name = json_file.stem
            try:
                plan = _load_template_from_path(json_file)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue  # skip malformed templates silently
            found[name] = (plan, source)

    result: list[dict[str, object]] = []
    for name, (plan, source) in sorted(found.items()):
        result.append(
            {
                "name": name,
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "variables": list(plan.variables.keys()),
                "source": source,
            }
        )
    return result


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
            output_artifact=step.output_artifact,
            required_inputs=step.required_inputs,
            on_failure=step.on_failure,
            spawn_mode=step.spawn_mode,
            condition=step.condition,
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
