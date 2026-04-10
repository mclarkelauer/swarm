"""MCP tools for the agent registry."""

from __future__ import annotations

import json

from swarm.mcp import state
from swarm.mcp.instance import mcp


@mcp.tool()
def registry_list() -> str:
    """List all registered agent definitions."""
    assert state.registry_api is not None
    agents = state.registry_api.list_agents()
    return json.dumps([a.to_dict() for a in agents])


@mcp.tool()
def registry_inspect(agent_id: str = "", name: str = "") -> str:
    """Get full details on an agent definition including provenance.

    Supply one of agent_id or name.
    """
    assert state.registry_api is not None
    if agent_id:
        info = state.registry_api.inspect(agent_id)
    elif name:
        defn = state.registry_api.resolve_agent(name)
        info = state.registry_api.inspect(defn.id)
    else:
        return json.dumps({"error": "Supply agent_id or name"})
    return json.dumps(info)


@mcp.tool()
def registry_search(query: str) -> str:
    """Search agent definitions by name or prompt substring."""
    assert state.registry_api is not None
    results = state.registry_api.search(query)
    return json.dumps([a.to_dict() for a in results])


@mcp.tool()
def registry_search_ranked(query: str, limit: str = "20") -> str:
    """Search agents with BM25 ranking and snippet highlighting.

    Returns ranked results with highlighted snippets showing where
    the query matched in each agent's name, description, prompt, or tags.

    Args:
        query: Search terms (space-separated, implicitly ANDed).
        limit: Maximum results to return (default 20).

    Returns:
        JSON array of {id, name, description, tags, rank, snippets}.
    """
    assert state.registry_api is not None
    results = state.registry_api.search_with_snippets(
        query, limit=int(limit)
    )
    return json.dumps(results)


@mcp.tool()
def registry_record_metric(
    agent_name: str,
    success: str = "true",
    duration_seconds: str = "0.0",
    tokens_used: str = "0",
    cost_usd: str = "0.0",
) -> str:
    """Record a performance metric for an agent.

    Accumulates metrics across runs for the given agent name.

    Args:
        agent_name: Agent name (stable across clones).
        success: "true" or "false".
        duration_seconds: Step duration.
        tokens_used: Tokens consumed.
        cost_usd: Cost in USD.

    Returns:
        JSON object with updated metrics.
    """
    assert state.registry_api is not None
    result = state.registry_api.record_metric(
        agent_name,
        success=success.lower() == "true",
        duration_seconds=float(duration_seconds),
        tokens_used=int(tokens_used),
        cost_usd=float(cost_usd),
    )
    return json.dumps(result)


@mcp.tool()
def registry_get_metrics(agent_name: str = "") -> str:
    """Get performance metrics for an agent or all agents.

    Args:
        agent_name: Agent name. Empty returns all agents' metrics.

    Returns:
        JSON object (single agent) or JSON array (all agents).
    """
    assert state.registry_api is not None
    if agent_name:
        result = state.registry_api.get_metrics(agent_name)
        if result is None:
            return json.dumps({"error": f"No metrics for '{agent_name}'"})
        return json.dumps(result)
    return json.dumps(state.registry_api.list_metrics())


@mcp.tool()
def registry_update(
    agent_id: str,
    description: str = "",
    tags: str = "",
    notes: str = "",
    status: str = "",
    working_dir: str = "",
) -> str:
    """Update metadata fields on an existing agent without cloning.

    Only non-structural fields can be updated in-place. For system_prompt,
    tools, or permissions changes, use forge_clone instead.

    Args:
        agent_id: ID of the agent to update.
        description: New description (empty = no change).
        tags: Comma-separated tags (empty = no change).
        notes: New notes (empty = no change).
        status: New status: active/draft/deprecated/archived (empty = no change).
        working_dir: New working directory (empty = no change).

    Returns:
        JSON object with the updated agent definition.
    """
    assert state.registry_api is not None
    updates: dict[str, str | int | list[str]] = {}
    if description:
        updates["description"] = description
    if tags:
        updates["tags"] = [t.strip() for t in tags.split(",")]
    if notes:
        updates["notes"] = notes
    if status:
        updates["status"] = status
    if working_dir:
        updates["working_dir"] = working_dir

    result = state.registry_api.update(agent_id, updates)
    if result is None:
        return json.dumps({"error": f"Agent '{agent_id}' not found"})
    return json.dumps(result.to_dict())


@mcp.tool()
def registry_remove(agent_id: str = "", name: str = "") -> str:
    """Remove an agent definition from the registry.

    Supply one of agent_id or name.
    """
    assert state.registry_api is not None
    if name and not agent_id:
        defn = state.registry_api.resolve_agent(name)
        agent_id = defn.id
    removed = state.registry_api.remove(agent_id)
    return json.dumps({"ok": removed, "agent_id": agent_id})
