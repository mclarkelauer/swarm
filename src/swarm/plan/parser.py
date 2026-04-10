"""Plan loading, validation, and saving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swarm.plan.conditions import validate_condition
from swarm.plan.models import Plan
from swarm.plan.versioning import next_version

if TYPE_CHECKING:
    from swarm.registry.api import RegistryAPI

_VALID_STEP_TYPES = {"task", "checkpoint", "loop", "fan_out", "join", "decision", "subplan"}
_VALID_ON_FAILURE = {"stop", "skip", "retry"}
_VALID_SPAWN_MODES = {"foreground", "background"}


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

        if step.type == "fan_out":
            if step.fan_out_config is None:
                errors.append(f"Fan-out step '{step.id}' must have fan_out_config")
            else:
                if len(step.fan_out_config.branches) < 2:
                    errors.append(
                        f"Fan-out step '{step.id}' must have at least 2 branches"
                    )
                for i, branch in enumerate(step.fan_out_config.branches):
                    if not branch.agent_type:
                        errors.append(
                            f"Fan-out step '{step.id}' branch {i} is missing agent_type"
                        )
                    if not branch.prompt:
                        errors.append(
                            f"Fan-out step '{step.id}' branch {i} is missing prompt"
                        )

        if step.type == "decision":
            if step.decision_config is None:
                errors.append(f"Decision step '{step.id}' must have decision_config")
            else:
                if not step.decision_config.actions:
                    errors.append(
                        f"Decision step '{step.id}' must have at least one action"
                    )
                for i, action in enumerate(step.decision_config.actions):
                    cond_err = validate_condition(action.condition)
                    if cond_err is not None:
                        errors.append(
                            f"Decision step '{step.id}' action {i}: {cond_err}"
                        )
                    for sid in action.activate_steps:
                        if sid not in step_ids:
                            errors.append(
                                f"Decision step '{step.id}' action {i}: "
                                f"activate_steps references unknown step '{sid}'"
                            )
                    for sid in action.skip_steps:
                        if sid not in step_ids:
                            errors.append(
                                f"Decision step '{step.id}' action {i}: "
                                f"skip_steps references unknown step '{sid}'"
                            )

        if step.type == "join" and not step.depends_on:
            errors.append(f"Join step '{step.id}' must have at least one depends_on")

        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append(
                    f"Step '{step.id}' depends on unknown step '{dep}'"
                )

        if step.on_failure not in _VALID_ON_FAILURE:
            errors.append(
                f"Step '{step.id}' has invalid on_failure '{step.on_failure}'; "
                f"must be one of {sorted(_VALID_ON_FAILURE)}"
            )

        if step.spawn_mode not in _VALID_SPAWN_MODES:
            errors.append(
                f"Step '{step.id}' has invalid spawn_mode '{step.spawn_mode}'; "
                f"must be one of {sorted(_VALID_SPAWN_MODES)}"
            )

        for inp in step.required_inputs:
            if not inp:
                errors.append(f"Step '{step.id}' has an empty string in required_inputs")

        cond_error = validate_condition(step.condition)
        if cond_error is not None:
            errors.append(f"Step '{step.id}': {cond_error}")

        if step.critic_agent and step.type != "task":
            errors.append(
                f"Step '{step.id}': critic_agent can only be set on task steps"
            )

        if step.critic_agent and step.max_critic_iterations < 1:
            errors.append(
                f"Step '{step.id}': max_critic_iterations must be >= 1"
            )

        if step.max_critic_iterations != 3 and not step.critic_agent:
            errors.append(
                f"Warning: Step '{step.id}': max_critic_iterations set without critic_agent"
            )

        if step.retry_config is not None and step.on_failure != "retry":
            errors.append(
                f"Step '{step.id}': retry_config is only valid when "
                f"on_failure is 'retry', got '{step.on_failure}'"
            )

        if step.retry_config is not None:
            rc = step.retry_config
            if rc.max_retries < 1:
                errors.append(
                    f"Step '{step.id}': retry_config.max_retries must be >= 1, "
                    f"got {rc.max_retries}"
                )
            if rc.backoff_seconds <= 0:
                errors.append(
                    f"Step '{step.id}': retry_config.backoff_seconds must be > 0, "
                    f"got {rc.backoff_seconds}"
                )
            if rc.backoff_multiplier <= 0:
                errors.append(
                    f"Step '{step.id}': retry_config.backoff_multiplier must be > 0, "
                    f"got {rc.backoff_multiplier}"
                )
            if rc.max_backoff_seconds <= 0:
                errors.append(
                    f"Step '{step.id}': retry_config.max_backoff_seconds must be > 0, "
                    f"got {rc.max_backoff_seconds}"
                )

    return errors


def validate_tool_policies(plan: Plan, registry_api: RegistryAPI) -> list[str]:
    """Check that each step's required_tools is a subset of the agent's tools.

    Returns a list of warning strings.  These are non-blocking warnings,
    not errors — agents may have empty tool lists.

    Args:
        plan: The plan to validate.
        registry_api: Registry API instance used to resolve agents.

    Returns:
        A list of warning strings (empty when no mismatches are found).
    """
    from swarm.errors import RegistryError

    warnings: list[str] = []
    for step in plan.steps:
        if not step.required_tools:
            continue
        if not step.agent_type:
            continue
        try:
            defn = registry_api.resolve_agent(step.agent_type)
        except RegistryError:
            # Agent not found — skip silently
            continue
        if not defn.tools:
            # Agent has no declared tools — skip silently
            continue
        agent_tools: set[str] = set(defn.tools)
        missing = set(step.required_tools) - agent_tools
        if missing:
            sorted_missing = sorted(missing)
            warnings.append(
                f"Step '{step.id}': agent '{step.agent_type}' is missing "
                f"required tools: {sorted_missing}"
            )
    return warnings


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
