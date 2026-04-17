"""Tests for swarm.mcp.discovery_tools: swarm_discover and swarm_health."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.context.api import SharedContextAPI
from swarm.experiments.api import ExperimentAPI
from swarm.forge.api import ForgeAPI
from swarm.mcp import state
from swarm.mcp.discovery_tools import swarm_discover, swarm_health
from swarm.mcp.forge_tools import forge_create
from swarm.memory.api import MemoryAPI
from swarm.messaging.api import MessageAPI
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> Iterator[None]:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")
    state.forge_api = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")
    try:
        yield
    finally:
        assert state.registry_api is not None
        state.registry_api.close()
        assert state.forge_api is not None
        state.forge_api.close()
        state.registry_api = None
        state.forge_api = None


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
        """Each result must have exactly id, name, description, tags, usage_count, failure_count, success_rate, status."""
        forge_create("my-agent", "Prompt.", description="Desc", tags='["t1"]')
        result = json.loads(swarm_discover())
        assert set(result[0].keys()) == {
            "id", "name", "description", "tags", "usage_count", "failure_count",
            "success_rate", "status",
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


class TestSwarmDiscoverStatusField:
    def test_results_include_status(self) -> None:
        forge_create("my-agent", "Prompt.")
        result = json.loads(swarm_discover())
        assert "status" in result[0]
        assert result[0]["status"] == "active"


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


class TestSwarmHealthCounts:
    """Round 5 follow-up: ``swarm_health`` exposes counts for every
    persistence subsystem so dashboards aren't asymmetric.

    Asserts presence and basic correctness of:
        agent_count, memory_count, message_count,
        experiment_count, context_count, tool_count.
    """

    @pytest.fixture()
    def _full_state(self, tmp_path: Path) -> Iterator[None]:
        # Augment the autouse registry/forge fixture with the four
        # additional APIs the count surface requires.
        state.memory_api = MemoryAPI(tmp_path / "memory.db")
        state.message_api = MessageAPI(tmp_path / "messages.db")
        state.experiment_api = ExperimentAPI(tmp_path / "experiments.db")
        state.context_api = SharedContextAPI(tmp_path / "context.db")
        try:
            yield
        finally:
            assert state.memory_api is not None
            state.memory_api.close()
            state.memory_api = None
            assert state.message_api is not None
            state.message_api.close()
            state.message_api = None
            assert state.experiment_api is not None
            state.experiment_api.close()
            state.experiment_api = None
            assert state.context_api is not None
            state.context_api.close()
            state.context_api = None

    def test_health_emits_all_five_counts(self, _full_state: None) -> None:
        result = json.loads(swarm_health())
        for key in (
            "agent_count",
            "memory_count",
            "message_count",
            "experiment_count",
            "context_count",
            "tool_count",
        ):
            assert key in result, f"swarm_health missing {key!r}: {result!r}"
            assert isinstance(result[key], int)

    def test_counts_reflect_inserted_rows(self, _full_state: None) -> None:
        # Insert one of each — counts should follow.
        forge_create("a-agent", "Prompt.")
        assert state.memory_api is not None
        state.memory_api.store(agent_name="a-agent", content="m", memory_type="episodic")
        assert state.message_api is not None
        state.message_api.send("a", "b", "hello", run_id="r1")
        assert state.experiment_api is not None
        state.experiment_api.create("exp", "v1", "v2")
        assert state.context_api is not None
        state.context_api.set("r1", "key", "value", set_by="a-agent")

        result = json.loads(swarm_health())
        assert result["agent_count"] == 1
        assert result["memory_count"] == 1
        assert result["message_count"] == 1
        assert result["experiment_count"] == 1
        assert result["context_count"] == 1

    def test_counts_omitted_when_apis_missing(self) -> None:
        # The autouse fixture sets only registry_api and forge_api, so
        # the partial state should still produce a valid response with
        # only agent_count and tool_count populated.
        result = json.loads(swarm_health())
        assert "agent_count" in result
        assert "tool_count" in result
        assert "memory_count" not in result
        assert "message_count" not in result
        assert "experiment_count" not in result
        assert "context_count" not in result
