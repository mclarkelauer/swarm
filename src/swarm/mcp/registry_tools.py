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
def registry_inspect(agent_id: str) -> str:
    """Get full details on an agent definition including provenance."""
    assert state.registry_api is not None
    info = state.registry_api.inspect(agent_id)
    return json.dumps(info)


@mcp.tool()
def registry_search(query: str) -> str:
    """Search agent definitions by name or prompt substring."""
    assert state.registry_api is not None
    results = state.registry_api.search(query)
    return json.dumps([a.to_dict() for a in results])


@mcp.tool()
def registry_remove(agent_id: str) -> str:
    """Remove an agent definition from the registry."""
    assert state.registry_api is not None
    removed = state.registry_api.remove(agent_id)
    return json.dumps({"ok": removed, "agent_id": agent_id})
