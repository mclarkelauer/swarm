"""Tests for the forge_diff MCP tool."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.forge_tools import forge_diff
from swarm.registry.api import RegistryAPI


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[RegistryAPI]:
    api = RegistryAPI(tmp_path / "registry.db")
    try:
        yield api
    finally:
        api.close()


@pytest.fixture(autouse=True)
def _set_state(api: RegistryAPI) -> Iterator[None]:
    state.registry_api = api
    try:
        yield
    finally:
        state.registry_api = None


class TestForgeDiff:
    def test_forge_diff_shows_changes(self, api: RegistryAPI) -> None:
        a = api.create("agent-a", "prompt alpha", [], [], description="desc A")
        b = api.create("agent-b", "prompt beta", [], [], description="desc B")
        result = json.loads(forge_diff(a.id, b.id))

        assert result["fields_changed"] > 0
        diffs = result["differences"]
        assert "system_prompt" in diffs
        assert diffs["system_prompt"]["a"] == "prompt alpha"
        assert diffs["system_prompt"]["b"] == "prompt beta"
        assert "description" in diffs
        assert diffs["description"]["a"] == "desc A"
        assert diffs["description"]["b"] == "desc B"

    def test_forge_diff_parent_child(self, api: RegistryAPI) -> None:
        parent = api.create("agent", "original prompt", [], [])
        child = api.clone(parent.id, {"name": "agent-v2", "system_prompt": "new prompt"})
        result = json.loads(forge_diff(parent.id, child.id))

        assert result["agent_a"]["version"] == 1
        assert result["agent_b"]["version"] == 2
        diffs = result["differences"]
        assert "version" in diffs
        assert diffs["version"]["a"] == 1
        assert diffs["version"]["b"] == 2
        assert "system_prompt" in diffs
        assert "name" in diffs

    def test_forge_diff_identical(self, api: RegistryAPI) -> None:
        a = api.create("same-agent", "same prompt", ["tool"], ["perm"])
        # Diff the agent with itself — id/created_at/parent_id are skipped
        result = json.loads(forge_diff(a.id, a.id))
        assert result["fields_changed"] == 0
        assert result["differences"] == {}

    def test_forge_diff_resolves_by_name(self, api: RegistryAPI) -> None:
        api.create("alpha-agent", "prompt A", [], [])
        api.create("beta-agent", "prompt B", [], [])
        result = json.loads(forge_diff("alpha-agent", "beta-agent"))
        assert result["agent_a"]["name"] == "alpha-agent"
        assert result["agent_b"]["name"] == "beta-agent"
        assert result["fields_changed"] > 0
