"""Tests for swarm.mcp.forge_tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.forge.api import ForgeAPI
from swarm.mcp import state
from swarm.mcp.forge_tools import (
    forge_clone,
    forge_create,
    forge_get,
    forge_list,
    forge_remove,
    forge_suggest,
)
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")
    state.forge_api = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")


class TestForgeList:
    def test_empty(self) -> None:
        result = json.loads(forge_list())
        assert result == []

    def test_lists_all(self) -> None:
        forge_create("a", "prompt a")
        forge_create("b", "prompt b")
        result = json.loads(forge_list())
        assert len(result) == 2

    def test_filters_by_name(self) -> None:
        forge_create("code-reviewer", "Reviews code.")
        forge_create("writer", "Writes docs.")
        result = json.loads(forge_list("review"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"


class TestForgeGet:
    def test_get_by_id(self) -> None:
        created = json.loads(forge_create("agent", "prompt"))
        result = json.loads(forge_get(agent_id=created["id"]))
        assert result["name"] == "agent"

    def test_get_by_name(self) -> None:
        forge_create("named-agent", "prompt")
        result = json.loads(forge_get(name="named-agent"))
        assert result["name"] == "named-agent"

    def test_not_found(self) -> None:
        result = json.loads(forge_get(agent_id="nonexistent"))
        assert "error" in result

    def test_no_params(self) -> None:
        result = json.loads(forge_get())
        assert "error" in result


class TestForgeCreate:
    def test_creates_agent(self) -> None:
        result = json.loads(forge_create("reviewer", "Reviews code.", '["Read"]', '["read"]'))
        assert result["name"] == "reviewer"
        assert result["id"]
        assert result["tools"] == ["Read"]
        assert result["permissions"] == ["read"]

    def test_default_tools_and_permissions(self) -> None:
        result = json.loads(forge_create("simple", "Does stuff."))
        assert result["tools"] == []
        assert result["permissions"] == []


class TestForgeClone:
    def test_clones_with_overrides(self) -> None:
        original = json.loads(forge_create("base", "Base prompt.", '["Read"]', '[]'))
        cloned = json.loads(forge_clone(original["id"], name="derived", system_prompt="New prompt."))
        assert cloned["name"] == "derived"
        assert cloned["system_prompt"] == "New prompt."
        assert cloned["parent_id"] == original["id"]

    def test_clone_keeps_original_when_no_override(self) -> None:
        original = json.loads(forge_create("base", "Base prompt.", '["Read"]', '["write"]'))
        cloned = json.loads(forge_clone(original["id"], name="copy"))
        assert cloned["tools"] == ["Read"]
        assert cloned["permissions"] == ["write"]


class TestForgeCloneByName:
    def test_clone_by_source_name(self) -> None:
        forge_create("base-agent", "Base prompt.", '["Read"]', '[]')
        cloned = json.loads(forge_clone(source_name="base-agent", name="derived"))
        assert cloned["name"] == "derived"
        assert cloned["system_prompt"] == "Base prompt."

    def test_clone_no_source(self) -> None:
        result = json.loads(forge_clone())
        assert "error" in result


class TestForgeSuggest:
    def test_finds_matching(self) -> None:
        forge_create("code-reviewer", "Reviews code quality.")
        forge_create("writer", "Writes documents.")
        result = json.loads(forge_suggest("review"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"

    def test_no_match(self) -> None:
        result = json.loads(forge_suggest("zzzzz"))
        assert result == []


class TestForgeRemove:
    def test_removes_existing(self) -> None:
        created = json.loads(forge_create("temp", "prompt"))
        result = json.loads(forge_remove(created["id"]))
        assert result["ok"] is True

    def test_returns_false_for_missing(self) -> None:
        result = json.loads(forge_remove("nonexistent"))
        assert result["ok"] is False
