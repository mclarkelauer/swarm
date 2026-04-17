"""MCP server — shared tool server for all agents in a swarm instance.

Public helpers
--------------
:func:`list_tools` and :func:`count_tools` introspect the FastMCP server
and return the live registry of tool names.  Use these instead of
hard-coding numbers in docs, prompts, or tests — the count drifts every
release as new tools are added.
"""

from __future__ import annotations

import asyncio


def _ensure_tools_registered() -> None:
    """Import every tool module so FastMCP sees their ``@mcp.tool`` calls.

    The MCP server's ``main()`` entry point performs these imports for
    runtime use; the helpers below mirror them so callers (tests, the
    health check, anything else) get the full registry without needing
    to start the server first.
    """
    # Each import is purely for side effects (decorator registration).
    import swarm.mcp.artifact_tools  # noqa: F401
    import swarm.mcp.context_tools  # noqa: F401
    import swarm.mcp.discovery_tools  # noqa: F401
    import swarm.mcp.executor_tools  # noqa: F401
    import swarm.mcp.experiment_tools  # noqa: F401
    import swarm.mcp.forge_tools  # noqa: F401
    import swarm.mcp.memory_tools  # noqa: F401
    import swarm.mcp.message_tools  # noqa: F401
    import swarm.mcp.plan_tools  # noqa: F401
    import swarm.mcp.registry_tools  # noqa: F401


def list_tools() -> list[str]:
    """Return the names of every MCP tool currently registered on the server.

    Names are returned in registration order. The list is deduplicated by
    construction since FastMCP rejects duplicate tool names at registration
    time, but callers that want defence-in-depth can assert
    ``len(set(list_tools())) == len(list_tools())``.
    """
    _ensure_tools_registered()
    from swarm.mcp.instance import mcp

    # FastMCP's public ``list_tools()`` is an async coroutine that
    # returns ``mcp.types.Tool`` objects with a stable ``name`` field.
    # Drive it with ``asyncio.run`` when no loop is running; otherwise
    # fall back to the private ``_tool_manager.list_tools()`` (sync)
    # so this helper is safe to call from within an active event loop.
    # The mcp[cli] dependency is pinned to ``>=1.0,<2.0`` in
    # ``pyproject.toml`` so the private path remains a tested escape
    # valve instead of an unbounded API risk.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        tools = asyncio.run(mcp.list_tools())
        return [t.name for t in tools]
    return [t.name for t in mcp._tool_manager.list_tools()]


def count_tools() -> int:
    """Return the number of MCP tools currently registered."""
    return len(list_tools())
