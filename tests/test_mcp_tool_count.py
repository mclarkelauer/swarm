"""Tests for the dynamic MCP tool registry helpers (`swarm.mcp.list_tools`).

These tests guard against count drift between docs/prompts/tests and the
actual FastMCP server.  If a new tool is added, only the floor below
needs to move — every other place that needs the number should call
``swarm.mcp.list_tools()`` or read it from ``swarm_health()``.
"""

from __future__ import annotations

import json

from swarm.mcp import count_tools, list_tools


# Floor for the tool count.  Bump this whenever you intentionally add a
# new MCP tool.  The assertion uses ``>=`` so adding tools never breaks
# the test — only removing one (or losing one to a registration bug)
# does.
_MIN_EXPECTED_TOOLS = 68


def test_list_tools_returns_at_least_min_expected() -> None:
    tools = list_tools()
    assert (
        len(tools) >= _MIN_EXPECTED_TOOLS
    ), f"Expected at least {_MIN_EXPECTED_TOOLS} MCP tools, got {len(tools)}: {tools}"


def test_list_tools_has_no_duplicates() -> None:
    tools = list_tools()
    assert len(set(tools)) == len(tools), (
        "Duplicate tool names registered: "
        f"{[name for name in tools if tools.count(name) > 1]}"
    )


def test_count_tools_matches_list_length() -> None:
    assert count_tools() == len(list_tools())


def test_known_tools_are_registered() -> None:
    """Spot-check a handful of tools from each category to catch wholesale
    module-import regressions (e.g. a typo in __init__'s side-effect imports).
    """
    tools = set(list_tools())
    expected_samples = {
        # forge
        "forge_create",
        "forge_clone",
        # plan
        "plan_create",
        "plan_execute_step",
        # executor
        "plan_run",
        "plan_run_status",
        # registry
        "registry_search",
        "registry_inspect",
        # artifacts
        "artifact_declare",
        # discovery
        "swarm_health",
        "swarm_discover",
        # memory
        "memory_store",
        "memory_recall",
        # messaging
        "agent_send_message",
        # context
        "context_set",
    }
    missing = expected_samples - tools
    assert not missing, f"Expected tools missing from registry: {missing}"


def test_swarm_health_reports_dynamic_tool_count() -> None:
    """swarm_health() output must include tool_count matching list_tools()."""
    from swarm.mcp.discovery_tools import swarm_health

    payload = json.loads(swarm_health())
    assert payload["tool_count"] == len(list_tools())
    assert payload["tool_count"] >= _MIN_EXPECTED_TOOLS
    # The full names list is also exposed for callers that want it.
    assert isinstance(payload["tools"], list)
    assert sorted(payload["tools"]) == sorted(list_tools())
