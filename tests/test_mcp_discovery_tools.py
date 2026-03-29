"""Tests for swarm.mcp.discovery_tools: swarm_discover."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.forge.api import ForgeAPI
from swarm.mcp import state
from swarm.mcp.discovery_tools import swarm_discover
from swarm.mcp.forge_tools import forge_create
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")
    state.forge_api = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")


class TestSwarmDiscoverEmpty:
    def test_empty_registry_returns_empty_list(self) -> None:
        result = json.loads(swarm_discover())
        assert result == []

    def test_empty_query_returns_all_agents(self) -> None:
        forge_create("agent-a", "Prompt A.", description="Alpha agent")
        forge_create("agent-b", "Prompt B.", description="Beta agent")
        result = json.loads(swarm_discover())
        assert len(result) == 2

    def test_empty_query_string_returns_all_agents(self) -> None:
        forge_create("agent-x", "Prompt X.")
        result = json.loads(swarm_discover(query=""))
        assert len(result) == 1


class TestSwarmDiscoverFiltering:
    def test_query_filters_by_name_match(self) -> None:
        forge_create("code-reviewer", "Reviews code.", description="Python code review")
        forge_create("doc-writer", "Writes docs.", description="Documentation writer")
        result = json.loads(swarm_discover(query="code"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"

    def test_query_filters_by_description_match(self) -> None:
        forge_create("agent-a", "Prompt A.", description="Analyzes security vulnerabilities")
        forge_create("agent-b", "Prompt B.", description="Writes documentation")
        result = json.loads(swarm_discover(query="security"))
        assert len(result) == 1
        assert result[0]["name"] == "agent-a"

    def test_query_filters_by_tags_match(self) -> None:
        forge_create("py-agent", "Prompt.", tags='["python", "testing"]')
        forge_create("go-agent", "Prompt.", tags='["golang", "performance"]')
        result = json.loads(swarm_discover(query="python"))
        assert len(result) == 1
        assert result[0]["name"] == "py-agent"

    def test_query_no_match_returns_empty_list(self) -> None:
        forge_create("agent-a", "Prompt A.")
        result = json.loads(swarm_discover(query="zzz-no-match-xyz"))
        assert result == []

    def test_query_matches_multiple_agents(self) -> None:
        forge_create("reviewer-one", "Reviews things.")
        forge_create("reviewer-two", "Also reviews things.")
        forge_create("writer", "Writes things.")
        result = json.loads(swarm_discover(query="reviewer"))
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"reviewer-one", "reviewer-two"}


class TestSwarmDiscoverResponseShape:
    def test_results_include_id(self) -> None:
        forge_create("my-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert "id" in result[0]
        assert result[0]["id"]  # non-empty

    def test_results_include_name(self) -> None:
        forge_create("my-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert result[0]["name"] == "my-agent"

    def test_results_include_description(self) -> None:
        forge_create("my-agent", "Prompt.", description="A useful agent")
        result = json.loads(swarm_discover())
        assert result[0]["description"] == "A useful agent"

    def test_results_include_tags(self) -> None:
        forge_create("my-agent", "Prompt.", tags='["alpha", "beta"]')
        result = json.loads(swarm_discover())
        assert result[0]["tags"] == ["alpha", "beta"]

    def test_results_never_include_system_prompt(self) -> None:
        """system_prompt must never appear in discover results."""
        forge_create("secret-agent", "TOP SECRET SYSTEM PROMPT")
        result = json.loads(swarm_discover())
        assert "system_prompt" not in result[0]

    def test_results_never_include_system_prompt_with_query(self) -> None:
        """system_prompt must never appear even when query is used."""
        forge_create("secret-agent", "TOP SECRET SYSTEM PROMPT", description="Classified")
        result = json.loads(swarm_discover(query="secret"))
        assert len(result) == 1
        assert "system_prompt" not in result[0]

    def test_results_have_expected_keys(self) -> None:
        """Each result must have exactly id, name, description, tags, usage_count, failure_count."""
        forge_create("my-agent", "Prompt.", description="Desc", tags='["t1"]')
        result = json.loads(swarm_discover())
        assert set(result[0].keys()) == {
            "id", "name", "description", "tags", "usage_count", "failure_count"
        }

    def test_tags_is_list_type(self) -> None:
        forge_create("my-agent", "Prompt.", tags='["x", "y"]')
        result = json.loads(swarm_discover())
        assert isinstance(result[0]["tags"], list)

    def test_empty_description_present_as_empty_string(self) -> None:
        forge_create("bare-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert result[0]["description"] == ""

    def test_empty_tags_present_as_empty_list(self) -> None:
        forge_create("bare-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert result[0]["tags"] == []


class TestSwarmDiscoverPerformanceFields:
    def test_results_include_usage_count(self) -> None:
        forge_create("my-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert "usage_count" in result[0]
        assert result[0]["usage_count"] == 0

    def test_results_include_failure_count(self) -> None:
        forge_create("my-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert "failure_count" in result[0]
        assert result[0]["failure_count"] == 0

    def test_results_never_include_system_prompt_after_schema_change(self) -> None:
        forge_create("secret-agent", "TOP SECRET")
        result = json.loads(swarm_discover())
        assert "system_prompt" not in result[0]

    def test_results_never_include_notes(self) -> None:
        """notes is an internal field; discover should not expose it."""
        forge_create("noted-agent", "Prompt.", notes="internal notes")
        result = json.loads(swarm_discover())
        assert "notes" not in result[0]

    def test_results_never_include_last_used(self) -> None:
        forge_create("dated-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert "last_used" not in result[0]


class TestSwarmDiscoverReturnType:
    def test_returns_json_string(self) -> None:
        raw = swarm_discover()
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert isinstance(parsed, list)

    def test_single_agent_returns_list_of_one(self) -> None:
        forge_create("solo-agent", "Only agent.")
        result = json.loads(swarm_discover())
        assert len(result) == 1
