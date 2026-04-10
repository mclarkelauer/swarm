"""MCP tools for the plan system."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from swarm.errors import PlanError, RegistryError
from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.plan.dag import detect_cycles, get_ready_steps
from swarm.plan.discovery import find_plans_dir
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import load_plan, save_plan, validate_plan, validate_tool_policies
from swarm.plan.run_log import load_run_log, write_run_log
from swarm.plan.templates import instantiate_template, list_templates
from swarm.plan.versioning import list_versions
from swarm.plan.visualization import render_ascii, render_mermaid


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
def plan_get_ready_steps(
    plan_json: str,
    completed_json: str = "[]",
    artifacts_dir: str = "",
    step_outcomes_json: str = "{}",
) -> str:
    """Get steps that are ready to execute (all dependencies met).

    Args:
        plan_json: Full plan JSON string.
        completed_json: JSON array of completed step ID strings.
        artifacts_dir: Optional path to the artifacts directory.  When
            provided, steps with ``required_inputs`` are only returned if
            every listed input file exists under this directory.
        step_outcomes_json: JSON object mapping step IDs to outcome strings
            (e.g. ``{"step-1": "failed"}``).  Used to evaluate
            ``step_failed:`` conditions.

    Returns:
        JSON array of step objects ready for execution.
    """
    data = json.loads(plan_json)
    plan = Plan.from_dict(data)
    completed: set[str] = set(json.loads(completed_json))
    art_dir = Path(artifacts_dir) if artifacts_dir else None
    outcomes: dict[str, str] = json.loads(step_outcomes_json) if step_outcomes_json else {}
    ready = get_ready_steps(plan, completed, artifacts_dir=art_dir, step_outcomes=outcomes or None)
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


def _safe_interpolate(template: str, variables: dict[str, str]) -> str:
    """Interpolate ``{key}`` placeholders in *template* from *variables*.

    Keys absent from *variables* are left as-is (no KeyError).
    """
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))
    return re.sub(r"\{(\w+)\}", _replacer, template)


@mcp.tool()
def plan_execute_step(
    plan_path: str,
    step_id: str,
    variables_json: str = "{}",
) -> str:
    """Resolve a plan step into an executable payload with prompt interpolation.

    Loads the plan from *plan_path*, merges plan-level variables with any
    caller-supplied overrides, interpolates the step prompt, and optionally
    enriches the payload with agent metadata from the registry.

    Args:
        plan_path: Filesystem path to the plan JSON file.
        step_id: ID of the step to execute.
        variables_json: JSON object of variable overrides.  Merged on top of
            plan-level variables (caller values win).

    Returns:
        JSON object with keys ``agent_type``, ``prompt``, ``spawn_mode``,
        ``output_artifact``, ``description``, ``tools``, and
        ``required_tools``.  ``description`` and ``tools`` are ``null`` when
        the agent cannot be resolved.  When the step has a ``critic_agent``
        set, a ``"critic"`` key is included with ``agent_type``,
        ``max_iterations``, and optionally ``description`` (resolved from the
        registry).  The ``"critic"`` key is omitted entirely when no
        ``critic_agent`` is configured.
        Returns ``{"error": "..."}`` for file-not-found, unknown step, or
        invalid *variables_json*.
    """
    # 1. Load plan
    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan file not found: {plan_path}"})

    # 2. Find step
    step = next((s for s in plan.steps if s.id == step_id), None)
    if step is None:
        return json.dumps({"error": f"Step '{step_id}' not found in plan"})

    # 3. Parse and merge variables
    try:
        overrides: dict[str, str] = json.loads(variables_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid variables_json: {exc}"})
    merged = {**plan.variables, **overrides}

    # 4. Handle fan_out step type
    if step.type == "fan_out":
        branches = []
        if step.fan_out_config is not None:
            for branch in step.fan_out_config.branches:
                branches.append(branch.to_dict())
        return json.dumps({
            "step_type": "fan_out",
            "branches": branches,
        })

    # 5. Handle join step type
    if step.type == "join":
        join_inputs = []
        for dep_id in step.depends_on:
            dep_step = next((s for s in plan.steps if s.id == dep_id), None)
            join_inputs.append({
                "step_id": dep_id,
                "output_artifact": dep_step.output_artifact if dep_step else "",
            })
        return json.dumps({
            "step_type": "join",
            "join_inputs": join_inputs,
        })

    # 6. Interpolate prompt
    prompt = _safe_interpolate(step.prompt, merged)

    # 7. Resolve agent from registry
    description: str | None = None
    tools: list[str] | None = None
    if state.registry_api is not None and step.agent_type:
        try:
            defn = state.registry_api.resolve_agent(step.agent_type)
            description = defn.description
            tools = list(defn.tools)
        except RegistryError:
            pass  # leave description/tools as None

    # 8. Build payload
    payload: dict[str, object] = {
        "agent_type": step.agent_type,
        "prompt": prompt,
        "spawn_mode": step.spawn_mode,
        "output_artifact": step.output_artifact,
        "description": description,
        "tools": tools,
        "required_tools": list(step.required_tools),
    }

    # 9. Attach critic block when critic_agent is configured
    if step.critic_agent:
        critic_description: str | None = None
        if state.registry_api is not None:
            try:
                critic_defn = state.registry_api.resolve_agent(step.critic_agent)
                critic_description = critic_defn.description
            except RegistryError:
                pass  # leave critic_description as None
        critic_block: dict[str, object] = {
            "agent_type": step.critic_agent,
            "max_iterations": step.max_critic_iterations,
        }
        if critic_description is not None:
            critic_block["description"] = critic_description
        payload["critic"] = critic_block

    return json.dumps(payload)


@mcp.tool()
def plan_validate_policies(plan_path: str) -> str:
    """Validate tool policies for a plan against the agent registry.

    For each step that declares ``required_tools``, checks whether the
    assigned agent's tool list is a superset of the required tools.  Returns
    non-blocking warnings — steps with agents that have no declared tools are
    silently skipped.

    Args:
        plan_path: Filesystem path to the plan JSON file.

    Returns:
        JSON ``{"warnings": [...]}`` — *warnings* is an empty array when
        every step's required tools are satisfied.  Returns
        ``{"error": "..."}`` if the plan file cannot be loaded.
    """
    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan file not found: {plan_path}"})

    if state.registry_api is None:
        return json.dumps({"warnings": []})

    warnings = validate_tool_policies(plan, state.registry_api)
    return json.dumps({"warnings": warnings})


@mcp.tool()
def plan_amend(plan_path: str, insert_after: str, new_steps_json: str) -> str:
    """Insert new steps into an existing plan immediately after a named step.

    Loads the plan from *plan_path*, validates the insertion point, wires
    dependencies for the new steps, rewires any downstream steps that
    depended on *insert_after* to instead depend on the last new step, then
    validates and saves the amended plan.

    Args:
        plan_path: Filesystem path to the plan JSON file.
        insert_after: ID of the existing step after which to insert.
        new_steps_json: JSON array of step objects to insert.  Each object
            follows the same schema as ``plan_create``'s ``steps_json``.
            New steps with no explicit ``depends_on`` automatically depend
            on the *insert_after* step.

    Returns:
        JSON ``{path, version, errors, inserted_steps}`` — *errors* is an
        empty array on success; *inserted_steps* lists the IDs of the newly
        inserted steps.
    """
    # 1. Load plan
    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan file not found: {plan_path}"})

    plans_dir = Path(plan_path).parent

    # 2. Find anchor step
    anchor_index = next(
        (i for i, s in enumerate(plan.steps) if s.id == insert_after), None
    )
    if anchor_index is None:
        return json.dumps({"error": f"Step '{insert_after}' not found in plan"})

    # 3. Parse new steps
    try:
        raw_new_steps: list[dict] = json.loads(new_steps_json)  # type: ignore[type-arg]
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid new_steps_json: {exc}"})

    new_steps: list[PlanStep] = [
        Plan.from_dict({"version": 1, "goal": "x", "steps": [s]}).steps[0]
        for s in raw_new_steps
    ]

    # 4. Validate no ID conflicts with existing steps
    existing_ids = {s.id for s in plan.steps}
    conflicts = [s.id for s in new_steps if s.id in existing_ids]
    if conflicts:
        return json.dumps({"error": f"Step IDs already exist in plan: {conflicts}"})

    # 5. Wire default dependencies: new steps with no explicit depends_on
    #    get depends_on set to (insert_after,).
    wired_new_steps: list[PlanStep] = []
    last_new_id = insert_after
    for step in new_steps:
        if not step.depends_on:
            d = step.to_dict()
            d["depends_on"] = [last_new_id]
            step = Plan.from_dict({"version": 1, "goal": "x", "steps": [d]}).steps[0]
        last_new_id = step.id
        wired_new_steps.append(step)

    # The actual last inserted step ID (used for rewiring downstream steps)
    final_new_id = wired_new_steps[-1].id

    # 6. Rewire downstream existing steps: any step that depended on
    #    insert_after should now depend on the last new step instead.
    rewired_existing: list[PlanStep] = []
    for step in plan.steps:
        if insert_after in step.depends_on:
            new_deps = tuple(
                final_new_id if dep == insert_after else dep
                for dep in step.depends_on
            )
            d = step.to_dict()
            d["depends_on"] = list(new_deps)
            step = Plan.from_dict({"version": 1, "goal": "x", "steps": [d]}).steps[0]
        rewired_existing.append(step)

    # 7. Build new step list: existing steps up to and including anchor,
    #    then new steps, then remaining existing steps (already rewired).
    new_step_list: list[PlanStep] = (
        rewired_existing[: anchor_index + 1]
        + wired_new_steps
        + rewired_existing[anchor_index + 1 :]
    )

    # 8. Build amended plan with incremented version
    amended_plan = Plan(
        version=plan.version + 1,
        goal=plan.goal,
        steps=new_step_list,
        variables=plan.variables,
        max_replans=plan.max_replans,
    )

    # 9. Validate
    errors = validate_plan(amended_plan)
    if not errors:
        try:
            detect_cycles(amended_plan)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return json.dumps({"path": None, "version": None, "errors": errors, "inserted_steps": []})

    # 10. Save
    saved_path = save_plan(amended_plan, plans_dir)
    return json.dumps({
        "path": str(saved_path),
        "version": amended_plan.version,
        "errors": [],
        "inserted_steps": [s.id for s in wired_new_steps],
    })


@mcp.tool()
def plan_patch_step(plan_path: str, step_id: str, overrides_json: str) -> str:
    """Patch individual fields of an existing plan step and save a new version.

    Loads the plan from *plan_path*, merges *overrides_json* onto the
    target step's current data, replaces the step in the plan, validates,
    increments the version, and saves.

    Args:
        plan_path: Filesystem path to the plan JSON file.
        step_id: ID of the step to patch.
        overrides_json: JSON object whose keys override the step's current
            field values.  Any field supported by ``PlanStep`` may be
            patched (e.g. ``prompt``, ``agent_type``, ``depends_on``).

    Returns:
        JSON ``{path, version, errors, patched_step}`` — *errors* is an
        empty array on success; *patched_step* echoes *step_id*.
    """
    # 1. Load plan
    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan file not found: {plan_path}"})

    plans_dir = Path(plan_path).parent

    # 2. Find step
    step_index = next((i for i, s in enumerate(plan.steps) if s.id == step_id), None)
    if step_index is None:
        return json.dumps({"error": f"Step '{step_id}' not found in plan"})

    # 3. Parse overrides
    try:
        overrides: dict[str, object] = json.loads(overrides_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid overrides_json: {exc}"})

    # 4. Merge and rebuild step
    step_data = plan.steps[step_index].to_dict()
    step_data.update(overrides)
    patched_step = Plan.from_dict({"version": 1, "goal": "x", "steps": [step_data]}).steps[0]

    # 5. Replace step in list
    new_steps = list(plan.steps)
    new_steps[step_index] = patched_step

    patched_plan = Plan(
        version=plan.version + 1,
        goal=plan.goal,
        steps=new_steps,
        variables=plan.variables,
        max_replans=plan.max_replans,
    )

    # 6. Validate
    errors = validate_plan(patched_plan)
    if not errors:
        try:
            detect_cycles(patched_plan)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return json.dumps({"path": None, "version": None, "errors": errors, "patched_step": step_id})

    # 7. Save
    saved_path = save_plan(patched_plan, plans_dir)
    return json.dumps({
        "path": str(saved_path),
        "version": patched_plan.version,
        "errors": [],
        "patched_step": step_id,
    })


@mcp.tool()
def plan_template_list() -> str:
    """List available plan templates.

    Scans builtin and user template directories (``~/.swarm/templates``) for
    ``*.json`` template files.  User templates override builtin templates when
    names collide.

    Returns:
        JSON array of ``{name, goal, step_count, variables, source}`` objects,
        where *source* is ``"builtin"`` or ``"user"``.
    """
    return json.dumps(list_templates())


@mcp.tool()
def plan_template_instantiate(
    template_name: str,
    variables_json: str = "{}",
    plans_dir: str = "",
) -> str:
    """Instantiate a plan template with variables and save it.

    Loads the named template, merges template default variables with
    *variables_json* (caller values win), interpolates all ``{key}``
    placeholders in step prompts and agent_type fields, validates the result,
    and saves it to *plans_dir*.

    Args:
        template_name: Name of the template (without ``.json`` extension).
            Run ``plan_template_list`` to see available templates.
        variables_json: JSON object of variable values to substitute.
            Caller values override template defaults.
        plans_dir: Directory to save the instantiated plan in (default:
            configured plans_dir).

    Returns:
        JSON ``{path, version, errors}`` — *errors* is an empty array on
        success.  Returns ``{"error": "..."}`` if the template is not found
        or instantiation fails validation.
    """
    try:
        variables: dict[str, str] = json.loads(variables_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid variables_json: {exc}"})

    try:
        plan = instantiate_template(template_name, variables)
    except PlanError as exc:
        return json.dumps({"error": str(exc)})

    target = _resolve_plans_dir(plans_dir)
    saved_path = save_plan(plan, target)
    return json.dumps({
        "path": str(saved_path),
        "version": plan.version,
        "errors": [],
    })


def _parse_duration(started_at: str, finished_at: str) -> float | None:
    """Return duration in seconds between two ISO timestamps, or None on failure."""
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        finish = datetime.fromisoformat(finished_at)
        return (finish - start).total_seconds()
    except (ValueError, TypeError):
        return None


@mcp.tool()
def plan_retrospective(run_log_path: str, plan_path: str = "") -> str:
    """Analyze a completed plan run and return structured insights.

    Loads a run log and its corresponding plan, then computes per-step timing,
    aggregate outcome counts, slowest steps, failing agents, unused artifacts,
    and actionable improvement suggestions.

    Args:
        run_log_path: Filesystem path to the run log JSON file.
        plan_path: Filesystem path to the plan JSON file.  When omitted the
            path stored inside the run log (``plan_path`` field) is used.

    Returns:
        JSON object with keys ``total_steps``, ``completed``, ``failed``,
        ``skipped``, ``slowest_steps``, ``failing_agents``,
        ``unused_artifacts``, and ``suggestions``.
        Returns ``{"error": "..."}`` on load failure.
    """
    # 1. Load run log
    try:
        log = load_run_log(Path(run_log_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    # Resolve plan path: explicit argument wins; fall back to value stored in log
    resolved_plan_path = plan_path or log.plan_path
    if not resolved_plan_path:
        return json.dumps({"error": "No plan_path provided and run log has no plan_path"})

    # 2. Load plan
    try:
        plan = load_plan(Path(resolved_plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan file not found: {resolved_plan_path}"})

    # 3. Build lookup maps from plan
    agent_by_step_id: dict[str, str] = {s.id: s.agent_type for s in plan.steps}

    # 4. Compute per-step analytics from run log
    step_durations: dict[str, float | None] = {}
    for outcome in log.steps:
        step_durations[outcome.step_id] = _parse_duration(
            outcome.started_at, outcome.finished_at
        )

    # 5. Compute aggregate counts
    total_steps = len(plan.steps)
    completed = sum(1 for s in log.steps if s.status == "completed")
    failed = sum(1 for s in log.steps if s.status == "failed")
    skipped = sum(1 for s in log.steps if s.status == "skipped")

    # 6. Slowest steps: sort by duration descending, top 3
    steps_with_duration = [
        (sid, dur) for sid, dur in step_durations.items() if dur is not None
    ]
    steps_with_duration.sort(key=lambda x: x[1], reverse=True)
    slowest_steps = [
        {
            "id": sid,
            "agent_type": agent_by_step_id.get(sid, ""),
            "duration_s": dur,
        }
        for sid, dur in steps_with_duration[:3]
    ]

    # 7. Failing agents: group failed steps by agent_type
    agent_failures: dict[str, list[str]] = {}
    for outcome in log.steps:
        if outcome.status == "failed":
            agent = agent_by_step_id.get(outcome.step_id, "")
            agent_failures.setdefault(agent, []).append(outcome.step_id)
    failing_agents = [
        {"agent_type": agent, "failures": len(step_ids), "step_ids": step_ids}
        for agent, step_ids in agent_failures.items()
    ]

    # 8. Unused artifacts: output_artifact values with no downstream consumer
    #    Only report when at least one step declares output_artifact.
    output_artifacts: list[tuple[str, str]] = [
        (s.output_artifact, s.id)
        for s in plan.steps
        if s.output_artifact
    ]
    unused_artifacts: list[dict[str, str]] = []
    if output_artifacts:
        # Collect all required_inputs values across all plan steps
        all_required_inputs: set[str] = set()
        for s in plan.steps:
            all_required_inputs.update(s.required_inputs)
        for artifact_path, producer_id in output_artifacts:
            if artifact_path not in all_required_inputs:
                unused_artifacts.append({"path": artifact_path, "step_id": producer_id})

    # 9. Generate suggestions
    suggestions: list[str] = []

    # Slowest step suggestion: steps with duration > 2x average
    valid_durations = [dur for dur in step_durations.values() if dur is not None]
    if valid_durations:
        avg_duration = sum(valid_durations) / len(valid_durations)
        if avg_duration > 0:
            for outcome in log.steps:
                dur = step_durations.get(outcome.step_id)
                if dur is not None and dur > 2 * avg_duration:
                    suggestions.append(
                        f"Step '{outcome.step_id}' took {dur:.1f}s — significantly above"
                        f" average ({avg_duration:.1f}s). Consider splitting."
                    )

    # Failing agent suggestions
    for entry in failing_agents:
        n = entry["failures"]
        suggestions.append(
            f"Agent '{entry['agent_type']}' failed {n} time(s) —"
            f" consider refining its prompt or notes."
        )

    # Unused artifact suggestions
    for ua in unused_artifacts:
        step_src = ua["step_id"]
        suggestions.append(
            f"Artifact '{ua['path']}' (from step '{step_src}') has no downstream consumer."
        )

    # 10. Compute cost summary from step outcomes
    total_tokens = sum(s.tokens_used for s in log.steps)
    total_cost_usd = sum(s.cost_usd for s in log.steps)

    return json.dumps({
        "total_steps": total_steps,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "slowest_steps": slowest_steps,
        "failing_agents": failing_agents,
        "unused_artifacts": unused_artifacts,
        "suggestions": suggestions,
    })


@mcp.tool()
def plan_visualize(
    plan_json: str,
    completed_json: str = "[]",
    format: str = "mermaid",
    step_outcomes_json: str = "{}",
) -> str:
    """Visualize a plan's DAG as a Mermaid flowchart or ASCII wave table.

    Args:
        plan_json: Full plan JSON string with version, goal, steps.
        completed_json: JSON array of completed step ID strings.
        format: Output format — ``"mermaid"`` for a Mermaid flowchart diagram,
            or ``"ascii"`` for a simple ASCII table grouped by execution wave.
        step_outcomes_json: JSON object mapping step IDs to outcome strings
            (e.g. ``{"step-1": "failed"}``).  Used for status color-coding.

    Returns:
        JSON ``{"format": "...", "diagram": "..."}``.
        Returns ``{"error": "..."}`` for invalid input.
    """
    try:
        data = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid plan_json: {exc}"})

    plan = Plan.from_dict(data)

    try:
        completed: set[str] = set(json.loads(completed_json))
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid completed_json: {exc}"})

    try:
        outcomes: dict[str, str] = json.loads(step_outcomes_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid step_outcomes_json: {exc}"})

    fmt = format.lower()
    if fmt == "mermaid":
        diagram = render_mermaid(plan, completed=completed, step_outcomes=outcomes)
    elif fmt == "ascii":
        diagram = render_ascii(plan, completed=completed, step_outcomes=outcomes)
    else:
        return json.dumps({"error": f"Unknown format '{format}'; use 'mermaid' or 'ascii'"})

    return json.dumps({"format": fmt, "diagram": diagram})


@mcp.tool()
def plan_replan(
    run_log_path: str,
    insert_after: str,
    new_steps_json: str,
) -> str:
    """Insert remediation steps into the active plan during execution.

    A convenience wrapper around ``plan_amend`` that:
    1. Loads the run log to find the active plan path.
    2. Checks the replan safety limit (``max_replans``).
    3. Increments the replan counter in the run log.
    4. Delegates to ``plan_amend`` for the actual insertion.

    Args:
        run_log_path: Path to the active run log JSON file.
        insert_after: ID of the step after which to insert new steps.
        new_steps_json: JSON array of step objects to insert.

    Returns:
        JSON ``{path, version, errors, inserted_steps, replan_count}``
        -- same as ``plan_amend`` plus the updated replan count.
        Returns ``{"error": "..."}`` if the replan limit is exceeded
        or the run log cannot be loaded.
    """
    # 1. Load run log
    try:
        log = load_run_log(Path(run_log_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    # 2. Load plan to check max_replans
    plan_path = log.plan_path
    if not plan_path:
        return json.dumps({"error": "Run log has no plan_path"})

    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan not found: {plan_path}"})

    # 3. Check safety limit
    if log.replan_count >= plan.max_replans:
        return json.dumps({
            "error": (
                f"Replan limit reached ({log.replan_count}/{plan.max_replans}). "
                f"Increase max_replans on the plan to allow more."
            ),
        })

    # 4. Delegate to plan_amend
    result_json = plan_amend(
        plan_path=plan_path,
        insert_after=insert_after,
        new_steps_json=new_steps_json,
    )
    result = json.loads(result_json)

    if result.get("errors"):
        return result_json  # pass through validation errors

    # 5. Increment replan counter and update run log
    log.replan_count += 1
    # Update plan_path to point to the new version
    if result.get("path"):
        log.plan_path = result["path"]
        log.plan_version = result["version"]
    write_run_log(log, Path(run_log_path))

    result["replan_count"] = log.replan_count
    return json.dumps(result)
