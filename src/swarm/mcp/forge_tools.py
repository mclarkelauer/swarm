"""MCP tools for the Agent Forge."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from swarm.errors import RegistryError
from swarm.forge.frontmatter import parse_frontmatter, render_frontmatter
from swarm.forge.ranking import build_ranking_prompt
from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.plan.parser import load_plan
from swarm.plan.run_log import load_run_log
from swarm.registry.models import AgentDefinition


def _agent_summary(a: AgentDefinition) -> dict:  # type: ignore[type-arg]
    """Return a to_dict() summary with system_prompt truncated to 80 chars."""
    d = a.to_dict()
    sp = d["system_prompt"]
    d["system_prompt"] = sp[:80] + ("..." if len(sp) > 80 else "")
    d["usage_count"] = a.usage_count
    d["failure_count"] = a.failure_count
    d["status"] = a.status
    return d


@mcp.tool()
def forge_list(name_filter: str = "") -> str:
    """List all agent definitions, optionally filtered by name substring."""
    assert state.forge_api is not None
    if name_filter:
        agents = state.forge_api.suggest_agent(name_filter)
    else:
        assert state.registry_api is not None
        agents = state.registry_api.list_agents()
    return json.dumps([_agent_summary(a) for a in agents])


@mcp.tool()
def forge_get(agent_id: str = "", name: str = "") -> str:
    """Get a single agent definition by ID or name.

    Supply one of agent_id or name.  If name is given, returns the first
    match from the cache/registry.
    """
    assert state.forge_api is not None
    assert state.registry_api is not None
    if agent_id:
        defn = state.registry_api.get(agent_id)
    elif name:
        defn = state.forge_api.get_cached(name)
    else:
        return json.dumps({"error": "Supply agent_id or name"})
    if defn is None:
        return json.dumps({"error": "Agent not found"})
    return json.dumps(defn.to_dict())


@mcp.tool()
def forge_create(
    name: str,
    system_prompt: str,
    tools: str = "[]",
    permissions: str = "[]",
    description: str = "",
    tags: str = "[]",
    notes: str = "",
) -> str:
    """Create and register a new agent definition.

    Args:
        name: Short agent type name (e.g. ``"code-reviewer"``).
        system_prompt: Full system prompt for the agent.
        tools: JSON array of tool name strings.
        permissions: JSON array of permission strings.
        description: Optional human-readable description of the agent.
        tags: JSON array of tag strings (e.g. ``'["python","review"]'``).
        notes: Optional freeform notes or lessons learned about this agent.

    Returns:
        JSON with the created agent definition including its ID.
    """
    assert state.forge_api is not None
    tool_list: list[str] = json.loads(tools) if tools else []
    perm_list: list[str] = json.loads(permissions) if permissions else []
    tag_list: list[str] = json.loads(tags) if tags else []
    defn = state.forge_api.create_agent(
        name, system_prompt, tool_list, perm_list,
        description=description, tags=tag_list, notes=notes,
    )
    return json.dumps(defn.to_dict())


@mcp.tool()
def forge_clone(
    source_id: str = "",
    source_name: str = "",
    name: str = "",
    system_prompt: str = "",
    tools: str = "",
    permissions: str = "",
    description: str = "",
    tags: str = "",
) -> str:
    """Clone an existing agent definition with optional overrides.

    Args:
        source_id: ID of the agent to clone.
        source_name: Name of the agent to clone (alternative to source_id).
        name: Override name (empty keeps the original).
        system_prompt: Override prompt (empty keeps the original).
        tools: Override tools as JSON array (empty keeps the original).
        permissions: Override permissions as JSON array (empty keeps the original).
        description: Override description (empty keeps the original).
        tags: Override tags as JSON array string (empty keeps the original).

    Returns:
        JSON with the new cloned agent definition.
    """
    assert state.forge_api is not None
    assert state.registry_api is not None
    if not source_id and source_name:
        defn = state.registry_api.resolve_agent(source_name)
        source_id = defn.id
    if not source_id:
        return json.dumps({"error": "Supply source_id or source_name"})
    overrides: dict[str, str | int | list[str]] = {}
    if name:
        overrides["name"] = name
    if system_prompt:
        overrides["system_prompt"] = system_prompt
    if tools:
        overrides["tools"] = json.loads(tools)
    if permissions:
        overrides["permissions"] = json.loads(permissions)
    if description:
        overrides["description"] = description
    if tags:
        overrides["tags"] = json.loads(tags)
    cloned = state.forge_api.clone_agent(source_id, overrides)
    return json.dumps(cloned.to_dict())


@mcp.tool()
def forge_suggest(query: str) -> str:
    """Search for existing agent definitions matching a task description.

    Searches across the registry and all source plugins by name and prompt.

    Returns:
        JSON array of matching agent definitions (system_prompt truncated to 80 chars).
    """
    assert state.forge_api is not None
    results = state.forge_api.suggest_agent(query)
    return json.dumps([_agent_summary(a) for a in results])


@mcp.tool()
def forge_suggest_ranked(query: str) -> str:
    """Search for agents and provide a ranking prompt for the orchestrator.

    Returns a JSON object with two keys:
    - ``candidates``: list of matching agent summaries (system_prompt truncated).
    - ``ranking_prompt``: a prompt the orchestrator can pass to an LLM to
      obtain a relevance ranking of the candidates.

    The orchestrator evaluates the ranking_prompt itself — Swarm stays
    LLM-agnostic.  When there are no candidates both values are empty.
    """
    assert state.forge_api is not None
    results = state.forge_api.suggest_agent(query)
    if not results:
        return json.dumps({"candidates": [], "ranking_prompt": ""})
    prompt = build_ranking_prompt(query, results)
    return json.dumps(
        {
            "candidates": [_agent_summary(a) for a in results],
            "ranking_prompt": prompt,
        }
    )


@mcp.tool()
def forge_remove(agent_id: str) -> str:
    """Remove an agent definition from the registry."""
    assert state.registry_api is not None
    removed = state.registry_api.remove(agent_id)
    return json.dumps({"ok": removed, "agent_id": agent_id})


@mcp.tool()
def forge_export_subagent(
    agent_id: str = "",
    name: str = "",
    output_dir: str = "",
) -> str:
    """Export an agent definition as a Claude Code ``.claude/agents/<name>.md`` file.

    Resolves the agent by ID or name, renders it as YAML-frontmatter Markdown,
    and writes the file to the target directory.

    Args:
        agent_id: UUID of the agent to export.
        name: Name (or unambiguous substring) of the agent to export.
        output_dir: Directory to write the ``.md`` file into.
            Defaults to ``<cwd>/.claude/agents``.

    Returns:
        JSON ``{"ok": true, "path": "<absolute_path>"}`` on success, or
        ``{"error": "<message>"}`` on failure.
    """
    assert state.registry_api is not None

    if not agent_id and not name:
        return json.dumps({"error": "Supply agent_id or name"})

    try:
        defn = state.registry_api.resolve_agent(agent_id or name)
    except RegistryError as exc:
        return json.dumps({"error": str(exc)})

    dest_dir = Path(output_dir) if output_dir else Path.cwd() / ".claude" / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)

    out_path = dest_dir / f"{defn.name}.md"
    out_path.write_text(render_frontmatter(defn), encoding="utf-8")

    return json.dumps({"ok": True, "path": str(out_path.resolve())})


@mcp.tool()
def forge_annotate_from_run(run_log_path: str, plan_path: str = "") -> str:
    """Update agent definitions with performance data from a completed run.

    Loads a run log and its associated plan, tallies completed and failed
    steps per agent type, then clones each agent definition with updated
    ``usage_count``, ``failure_count``, ``last_used``, and (on failures)
    appended ``notes``.

    Args:
        run_log_path: Path to the run-log JSON file produced by the executor.
        plan_path: Path to the plan JSON file.  If omitted, the path stored
            inside the run log (``log.plan_path``) is used.

    Returns:
        JSON with three lists:

        - ``annotated``: agents that were updated — each entry has
          ``name``, ``new_id``, ``usage_delta``, ``failure_delta``.
        - ``unchanged``: agent names that appeared in the plan but had
          zero steps recorded in the run log.
        - ``skipped``: agent types that could not be resolved in the
          registry.
    """
    assert state.registry_api is not None
    assert state.forge_api is not None

    # 1. Load run log
    run_log_file = Path(run_log_path)
    if not run_log_file.exists():
        return json.dumps({"error": f"Run log not found: {run_log_path}"})
    try:
        log = load_run_log(run_log_file)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Failed to load run log: {exc}"})

    # 2. Resolve plan path
    resolved_plan_path = plan_path or log.plan_path
    if not resolved_plan_path:
        return json.dumps({"error": "No plan_path provided and run log has no plan_path"})
    plan_file = Path(resolved_plan_path)
    if not plan_file.exists():
        return json.dumps({"error": f"Plan not found: {resolved_plan_path}"})
    try:
        plan = load_plan(plan_file)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Failed to load plan: {exc}"})

    # 3. Build step_id → agent_type mapping from plan
    step_agent_map: dict[str, str] = {}
    for step in plan.steps:
        if step.agent_type:
            step_agent_map[step.id] = step.agent_type

    # Collect all unique agent types referenced in the plan
    all_agent_types: set[str] = set(step_agent_map.values())

    # 4. Tally outcomes per agent type
    completed_by_agent: dict[str, int] = {at: 0 for at in all_agent_types}
    failed_by_agent: dict[str, int] = {at: 0 for at in all_agent_types}
    failure_msgs_by_agent: dict[str, list[str]] = {at: [] for at in all_agent_types}

    for outcome in log.steps:
        agent_type = step_agent_map.get(outcome.step_id)
        if agent_type is None:
            # Step not in plan — skip
            continue
        if outcome.status == "completed":
            completed_by_agent[agent_type] += 1
        elif outcome.status == "failed":
            failed_by_agent[agent_type] += 1
            msg = f"step {outcome.step_id}"
            if outcome.message:
                msg += f": {outcome.message}"
            failure_msgs_by_agent[agent_type].append(msg)

    # 5. Annotate each agent type
    annotated: list[dict[str, object]] = []
    unchanged: list[str] = []
    skipped: list[str] = []

    now_iso = datetime.now(UTC).isoformat()

    for agent_type in sorted(all_agent_types):
        completed = completed_by_agent[agent_type]
        failed = failed_by_agent[agent_type]
        total = completed + failed

        # 6. Agents with zero steps → unchanged
        if total == 0:
            unchanged.append(agent_type)
            continue

        # Resolve from registry
        try:
            original = state.registry_api.resolve_agent(agent_type)
        except RegistryError:
            skipped.append(agent_type)
            continue

        overrides: dict[str, str | int | list[str]] = {
            "usage_count": original.usage_count + total,
            "last_used": now_iso,
        }

        if failed > 0:
            overrides["failure_count"] = original.failure_count + failed
            failure_summary = "; ".join(failure_msgs_by_agent[agent_type])
            overrides["notes"] = original.notes + "\nRun annotation: " + failure_summary
        else:
            overrides["failure_count"] = original.failure_count

        cloned = state.forge_api.clone_agent(original.id, overrides)
        annotated.append(
            {
                "name": agent_type,
                "new_id": cloned.id,
                "usage_delta": total,
                "failure_delta": failed,
            }
        )

    return json.dumps({"annotated": annotated, "unchanged": unchanged, "skipped": skipped})


@mcp.tool()
def forge_import_subagents(project_dir: str = "") -> str:
    """Import Claude Code subagent ``.md`` files into the Swarm registry.

    Scans ``<project_dir>/.claude/agents/*.md`` (defaults to cwd), parses
    YAML frontmatter, and registers each agent that does not already exist.

    Field mapping:
    - ``name`` (required) — skip file if missing
    - ``description`` — optional, defaults to ``""``
    - ``tools`` — optional, defaults to ``[]``
    - body — becomes ``system_prompt``

    Args:
        project_dir: Root of the project to import from.  Defaults to cwd.

    Returns:
        JSON ``{"imported": [...], "skipped": [...], "errors": [...]}``
        where each list holds agent names (or ``"<filename>: <reason>"``
        for errors).
    """
    assert state.forge_api is not None
    assert state.registry_api is not None

    agents_dir = Path(project_dir or ".") / ".claude" / "agents"
    imported: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    if not agents_dir.exists():
        return json.dumps({"imported": imported, "skipped": skipped, "errors": errors})

    for md_file in sorted(agents_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(text)

            name = metadata.get("name")
            if not name or not isinstance(name, str) or not name.strip():
                errors.append(f"{md_file.name}: missing 'name' in frontmatter")
                continue
            name = name.strip()

            description_raw = metadata.get("description", "")
            description = description_raw if isinstance(description_raw, str) else ""

            tools_raw = metadata.get("tools", [])
            tools: list[str] = list(tools_raw) if isinstance(tools_raw, list) else []

            # Exact-match conflict check
            existing = state.registry_api.list_agents(name_filter=name)
            if any(a.name == name for a in existing):
                skipped.append(name)
                continue

            state.forge_api.create_agent(
                name=name,
                system_prompt=body,
                tools=tools,
                permissions=[],
                description=description,
            )
            imported.append(name)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"{md_file.name}: {exc}")

    return json.dumps({"imported": imported, "skipped": skipped, "errors": errors})
