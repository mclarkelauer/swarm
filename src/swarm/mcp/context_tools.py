"""MCP tools for run-scoped shared context."""

from __future__ import annotations

import json

from swarm.mcp import state
from swarm.mcp.instance import mcp


@mcp.tool()
def context_set(
    run_id: str,
    key: str,
    value: str,
    set_by: str = "",
) -> str:
    """Set a key-value pair in the run's shared context.

    The shared context is a blackboard that any agent in the same
    plan run can read and write.  Use it for structured data sharing
    without file artifacts.

    Args:
        run_id: The plan run identifier.
        key: Context key (e.g. "api_schema", "test_results").
        value: Value to store (typically JSON-encoded).
        set_by: Name of the agent/step setting this value.

    Returns:
        JSON object confirming the stored entry.
    """
    assert state.context_api is not None
    result = state.context_api.set(run_id, key, value, set_by=set_by)
    return json.dumps(result)


@mcp.tool()
def context_get(run_id: str, key: str) -> str:
    """Get a value from the run's shared context.

    Args:
        run_id: The plan run identifier.
        key: Context key to look up.

    Returns:
        JSON object: {"key": "...", "value": "..."} or {"key": "...", "value": null}.
    """
    assert state.context_api is not None
    value = state.context_api.get(run_id, key)
    return json.dumps({"key": key, "value": value})


@mcp.tool()
def context_get_all(run_id: str) -> str:
    """Get all key-value pairs from the run's shared context.

    Args:
        run_id: The plan run identifier.

    Returns:
        JSON object mapping keys to values.
    """
    assert state.context_api is not None
    all_ctx = state.context_api.get_all(run_id)
    return json.dumps(all_ctx)


@mcp.tool()
def context_delete(run_id: str, key: str) -> str:
    """Delete a key from the run's shared context.

    Args:
        run_id: The plan run identifier.
        key: Context key to delete.

    Returns:
        JSON object: {"ok": true/false, "key": "..."}.
    """
    assert state.context_api is not None
    deleted = state.context_api.delete(run_id, key)
    return json.dumps({"ok": deleted, "key": key})
