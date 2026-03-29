"""Tests for swarm.forge.api: ForgeAPI."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.errors import RegistryError
from swarm.forge.api import ForgeAPI
from swarm.forge.cache import read_cache
from swarm.registry.models import AgentDefinition
from swarm.registry.sources import SourcePlugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubSource(SourcePlugin):
    """In-memory source plugin for testing."""

    def __init__(self, source_name: str, agents: list[AgentDefinition]) -> None:
        self._name = source_name
        self._agents = agents

    @property
    def name(self) -> str:
        return self._name

    def search(self, query: str) -> list[AgentDefinition]:
        return [a for a in self._agents if query.lower() in a.name.lower()
                or query.lower() in a.system_prompt.lower()]

    def install(self, name: str) -> AgentDefinition:
        for a in self._agents:
            if a.name == name:
                return a
        raise RegistryError(f"Not found: {name}")


def _make_defn(agent_id: str, name: str, prompt: str = "prompt") -> AgentDefinition:
    return AgentDefinition(id=agent_id, name=name, system_prompt=prompt)


@pytest.fixture()
def forge(tmp_path: Path) -> ForgeAPI:
    return ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")


class TestCreateAgent:
    def test_returns_definition(self, forge: ForgeAPI) -> None:
        d = forge.create_agent("reviewer", "Reviews code.", ["bash"], ["read"])
        assert d.name == "reviewer"
        assert d.source == "forge"
        assert d.id

    def test_caches_definition(self, forge: ForgeAPI, tmp_path: Path) -> None:
        forge.create_agent("reviewer", "prompt", [], [])
        cached = read_cache(tmp_path / "forge", "reviewer")
        assert cached is not None
        assert cached.name == "reviewer"

    def test_registers_in_db(self, forge: ForgeAPI) -> None:
        d = forge.create_agent("worker", "prompt", [], [])
        found = forge.get_cached("worker")
        assert found is not None
        assert found.id == d.id

    def test_create_agent_with_description_and_tags(self, forge: ForgeAPI) -> None:
        d = forge.create_agent(
            "py-reviewer",
            "Reviews Python code.",
            [],
            [],
            description="Checks Python style",
            tags=["python", "review"],
        )
        assert d.description == "Checks Python style"
        assert d.tags == ("python", "review")


class TestCloneAgent:
    def test_clone_preserves_provenance(self, forge: ForgeAPI) -> None:
        original = forge.create_agent("base", "prompt", ["tool"], ["perm"])
        clone = forge.clone_agent(original.id, {"name": "derived"})
        assert clone.parent_id == original.id
        assert clone.name == "derived"

    def test_clone_caches(self, forge: ForgeAPI, tmp_path: Path) -> None:
        original = forge.create_agent("base", "prompt", [], [])
        forge.clone_agent(original.id, {"name": "clone"})
        cached = read_cache(tmp_path / "forge", "clone")
        assert cached is not None

    def test_clone_missing_raises(self, forge: ForgeAPI) -> None:
        with pytest.raises(RegistryError):
            forge.clone_agent("nonexistent", {"name": "x"})


class TestSuggestAgent:
    def test_finds_matching(self, forge: ForgeAPI) -> None:
        forge.create_agent("code-reviewer", "Reviews code quality.", [], [])
        forge.create_agent("writer", "Writes documents.", [], [])
        results = forge.suggest_agent("review")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_no_match(self, forge: ForgeAPI) -> None:
        forge.create_agent("worker", "Does work.", [], [])
        assert forge.suggest_agent("zzzzz") == []


class TestGetCached:
    def test_cache_hit(self, forge: ForgeAPI) -> None:
        forge.create_agent("cached-agent", "prompt", [], [])
        result = forge.get_cached("cached-agent")
        assert result is not None
        assert result.name == "cached-agent"

    def test_fallback_to_registry(self, forge: ForgeAPI, tmp_path: Path) -> None:
        forge.create_agent("db-only", "prompt", [], [])
        # Remove from cache
        cache_file = tmp_path / "forge" / "db-only.json"
        if cache_file.exists():
            cache_file.unlink()
        result = forge.get_cached("db-only")
        assert result is not None

    def test_miss(self, forge: ForgeAPI) -> None:
        assert forge.get_cached("nonexistent") is None


class TestSuggestAgentWithSources:
    """Tests for suggest_agent when source plugins are registered."""

    def test_source_results_included(self, tmp_path: Path) -> None:
        source = _StubSource("stub", [_make_defn("ext-1", "linter", "Lints code.")])
        forge = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge", sources=[source])
        results = forge.suggest_agent("lint")
        assert len(results) == 1
        assert results[0].name == "linter"

    def test_registry_and_source_combined(self, tmp_path: Path) -> None:
        source = _StubSource("stub", [_make_defn("ext-1", "external-reviewer", "Reviews.")])
        forge = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge", sources=[source])
        forge.create_agent("internal-reviewer", "Reviews code quality.", [], [])
        results = forge.suggest_agent("review")
        names = {r.name for r in results}
        assert "internal-reviewer" in names
        assert "external-reviewer" in names

    def test_registry_results_come_first(self, tmp_path: Path) -> None:
        source = _StubSource("stub", [_make_defn("ext-1", "reviewer", "Reviews.")])
        forge = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge", sources=[source])
        reg_defn = forge.create_agent("reviewer-pro", "Reviews code.", [], [])
        results = forge.suggest_agent("review")
        # Registry hit should be first
        assert results[0].id == reg_defn.id

    def test_deduplicates_by_id(self, tmp_path: Path) -> None:
        shared_defn = _make_defn("same-id", "dup-agent", "Does stuff.")
        source_a = _StubSource("a", [shared_defn])
        source_b = _StubSource("b", [shared_defn])
        forge = ForgeAPI(
            tmp_path / "registry.db", tmp_path / "forge",
            sources=[source_a, source_b],
        )
        results = forge.suggest_agent("dup")
        assert len(results) == 1
        assert results[0].id == "same-id"

    def test_multiple_sources_aggregated(self, tmp_path: Path) -> None:
        source_a = _StubSource("a", [_make_defn("a-1", "tester", "Tests code.")])
        source_b = _StubSource("b", [_make_defn("b-1", "test-writer", "Writes tests.")])
        forge = ForgeAPI(
            tmp_path / "registry.db", tmp_path / "forge",
            sources=[source_a, source_b],
        )
        results = forge.suggest_agent("test")
        names = {r.name for r in results}
        assert "tester" in names
        assert "test-writer" in names

    def test_empty_sources_still_queries_registry(self, tmp_path: Path) -> None:
        empty = _StubSource("empty", [])
        forge = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge", sources=[empty])
        forge.create_agent("worker", "Does work.", [], [])
        results = forge.suggest_agent("work")
        assert len(results) == 1
        assert results[0].name == "worker"

    def test_no_sources_backward_compatible(self, tmp_path: Path) -> None:
        forge = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")
        forge.create_agent("agent", "Does things.", [], [])
        results = forge.suggest_agent("thing")
        assert len(results) == 1
