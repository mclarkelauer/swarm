"""MCP tools for lightweight agent catalog discovery."""

from __future__ import annotations

import json

from swarm.mcp import state
from swarm.mcp.instance import mcp


@mcp.tool()
def swarm_discover(query: str = "") -> str:
    """Discover agents by name, description, and tags — without full system prompts.

    Returns lightweight catalog entries for browsing. Use forge_get for full details.

    Args:
        query: Search string to filter by name/description/tags. Empty returns all.

    Returns:
        JSON array of {id, name, description, tags} objects. Never includes system_prompt.
    """
    assert state.registry_api is not None
    agents = state.registry_api.search(query) if query else state.registry_api.list_agents()
    return json.dumps(
        [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "tags": list(a.tags),
                "usage_count": a.usage_count,
                "failure_count": a.failure_count,
            }
            for a in agents
        ]
    )
