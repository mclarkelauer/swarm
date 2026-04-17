"""MCP tools for lightweight agent catalog discovery."""

from __future__ import annotations

import importlib.metadata
import json

from swarm.mcp import list_tools, state
from swarm.mcp.instance import mcp


@mcp.tool()
def swarm_health() -> str:
    """Check Swarm system health and configuration.

    Returns database sizes, agent/memory counts, version info, and the
    live MCP tool count (introspected from the FastMCP registry — never
    hard-coded).

    Returns:
        JSON object with system health information.
    """
    health: dict[str, object] = {
        "status": "ok",
    }

    # Version
    try:
        health["version"] = importlib.metadata.version("swarm-mcp")
    except importlib.metadata.PackageNotFoundError:
        health["version"] = "unknown"

    # MCP tool count — introspected from the FastMCP server, so the
    # number stays accurate as tools are added or removed.
    tools = list_tools()
    health["tool_count"] = len(tools)
    health["tools"] = tools

    # Agent count
    if state.registry_api is not None:
        agents = state.registry_api.list_agents()
        health["agent_count"] = len(agents)
        agents_by_source: dict[str, int] = {}
        for a in agents:
            src = a.source
            agents_by_source[src] = agents_by_source.get(src, 0) + 1
        health["agents_by_source"] = agents_by_source

    # Memory count
    if state.memory_api is not None:
        health["memory_count"] = state.memory_api.count()

    # Plans directory
    if state.plans_dir:
        from pathlib import Path

        plans_path = Path(state.plans_dir)
        if plans_path.exists():
            plan_files = list(plans_path.glob("*.json"))
            health["plan_count"] = len(plan_files)
            health["plans_dir"] = state.plans_dir

    return json.dumps(health)


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
                "success_rate": a.success_rate,
                "status": a.status,
            }
            for a in agents
        ]
    )
