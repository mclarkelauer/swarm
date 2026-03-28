"""MCP tools for the Agent Forge."""

from __future__ import annotations

import json

from swarm.mcp import state
from swarm.mcp.instance import mcp


@mcp.tool()
def forge_list(name_filter: str = "") -> str:
    """List all agent definitions, optionally filtered by name substring."""
    assert state.forge_api is not None
    if name_filter:
        agents = state.forge_api.suggest_agent(name_filter)
    else:
        assert state.registry_api is not None
        agents = state.registry_api.list_agents()
    return json.dumps([a.to_dict() for a in agents])


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
) -> str:
    """Create and register a new agent definition.

    Args:
        name: Short agent type name (e.g. ``"code-reviewer"``).
        system_prompt: Full system prompt for the agent.
        tools: JSON array of tool name strings.
        permissions: JSON array of permission strings.

    Returns:
        JSON with the created agent definition including its ID.
    """
    assert state.forge_api is not None
    tool_list: list[str] = json.loads(tools) if tools else []
    perm_list: list[str] = json.loads(permissions) if permissions else []
    defn = state.forge_api.create_agent(name, system_prompt, tool_list, perm_list)
    return json.dumps(defn.to_dict())


@mcp.tool()
def forge_clone(
    source_id: str,
    name: str = "",
    system_prompt: str = "",
    tools: str = "",
    permissions: str = "",
) -> str:
    """Clone an existing agent definition with optional overrides.

    Args:
        source_id: ID of the agent to clone.
        name: Override name (empty keeps the original).
        system_prompt: Override prompt (empty keeps the original).
        tools: Override tools as JSON array (empty keeps the original).
        permissions: Override permissions as JSON array (empty keeps the original).

    Returns:
        JSON with the new cloned agent definition.
    """
    assert state.forge_api is not None
    overrides: dict[str, str | list[str]] = {}
    if name:
        overrides["name"] = name
    if system_prompt:
        overrides["system_prompt"] = system_prompt
    if tools:
        overrides["tools"] = json.loads(tools)
    if permissions:
        overrides["permissions"] = json.loads(permissions)
    defn = state.forge_api.clone_agent(source_id, overrides)
    return json.dumps(defn.to_dict())


@mcp.tool()
def forge_suggest(query: str) -> str:
    """Search for existing agent definitions matching a task description.

    Searches across the registry and all source plugins by name and prompt.

    Returns:
        JSON array of matching agent definitions.
    """
    assert state.forge_api is not None
    results = state.forge_api.suggest_agent(query)
    return json.dumps([a.to_dict() for a in results])


@mcp.tool()
def forge_remove(agent_id: str) -> str:
    """Remove an agent definition from the registry."""
    assert state.registry_api is not None
    removed = state.registry_api.remove(agent_id)
    return json.dumps({"ok": removed, "agent_id": agent_id})
