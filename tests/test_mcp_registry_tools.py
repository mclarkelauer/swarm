"""Tests for swarm.mcp.registry_tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.registry_tools import (
    registry_inspect,
    registry_list,
    registry_remove,
    registry_search,
)
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")


class TestRegistryList:
    def test_empty_initially(self) -> None:
        result = json.loads(registry_list())
        assert result == []

    def test_lists_created_agents(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("researcher", "prompt", ["tool"], ["perm"])
        result = json.loads(registry_list())
        assert len(result) == 1
        assert result[0]["name"] == "researcher"


class TestRegistryInspect:
    def test_returns_details(self) -> None:
        assert state.registry_api is not None
        d = state.registry_api.create("agent", "prompt", [], [])
        result = json.loads(registry_inspect(d.id))
        assert result["name"] == "agent"
        assert "provenance_chain" in result

    def test_inspect_by_name(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("named-agent", "prompt", [], [])
        result = json.loads(registry_inspect(name="named-agent"))
        assert result["name"] == "named-agent"

    def test_inspect_no_params(self) -> None:
        result = json.loads(registry_inspect())
        assert "error" in result


class TestRegistrySearch:
    def test_finds_matching(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("code-reviewer", "Reviews code.", [], [])
        state.registry_api.create("writer", "Writes docs.", [], [])
        result = json.loads(registry_search("review"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"

    def test_no_match(self) -> None:
        result = json.loads(registry_search("zzzzz"))
        assert result == []


class TestRegistryRemove:
    def test_removes_existing(self) -> None:
        assert state.registry_api is not None
        d = state.registry_api.create("temp", "prompt", [], [])
        result = json.loads(registry_remove(d.id))
        assert result["ok"] is True
        assert state.registry_api.get(d.id) is None

    def test_removes_by_name(self) -> None:
        assert state.registry_api is not None
        d = state.registry_api.create("named-temp", "prompt", [], [])
        result = json.loads(registry_remove(name="named-temp"))
        assert result["ok"] is True
        assert state.registry_api.get(d.id) is None

    def test_returns_false_for_missing(self) -> None:
        result = json.loads(registry_remove("nonexistent"))
        assert result["ok"] is False
