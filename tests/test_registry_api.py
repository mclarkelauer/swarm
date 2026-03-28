"""Tests for swarm.registry.api: RegistryAPI."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.errors import RegistryError
from swarm.registry.api import RegistryAPI


@pytest.fixture()
def api(tmp_path: Path) -> RegistryAPI:
    return RegistryAPI(tmp_path / "registry.db")


class TestCreate:
    def test_create_returns_definition(self, api: RegistryAPI) -> None:
        d = api.create("researcher", "You research.", ["web_search"], ["read"])
        assert d.name == "researcher"
        assert d.system_prompt == "You research."
        assert "web_search" in d.tools
        assert "read" in d.permissions
        assert d.id
        assert d.created_at

    def test_create_default_source(self, api: RegistryAPI) -> None:
        d = api.create("test", "prompt", [], [])
        assert d.source == "forge"

    def test_create_no_parent(self, api: RegistryAPI) -> None:
        d = api.create("test", "prompt", [], [])
        assert d.parent_id is None


class TestGet:
    def test_get_existing(self, api: RegistryAPI) -> None:
        d = api.create("test", "prompt", [], [])
        found = api.get(d.id)
        assert found is not None
        assert found.id == d.id
        assert found.name == d.name

    def test_get_missing(self, api: RegistryAPI) -> None:
        assert api.get("nonexistent") is None


class TestList:
    def test_list_all(self, api: RegistryAPI) -> None:
        api.create("alpha", "p", [], [])
        api.create("beta", "p", [], [])
        assert len(api.list_agents()) == 2

    def test_list_with_filter(self, api: RegistryAPI) -> None:
        api.create("researcher", "p", [], [])
        api.create("writer", "p", [], [])
        result = api.list_agents(name_filter="research")
        assert len(result) == 1
        assert result[0].name == "researcher"

    def test_list_empty(self, api: RegistryAPI) -> None:
        assert api.list_agents() == []


class TestSearch:
    def test_search_by_name(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [])
        api.create("writer", "Writes docs.", [], [])
        results = api.search("review")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_prompt(self, api: RegistryAPI) -> None:
        api.create("agent-a", "Handles security audits.", [], [])
        results = api.search("security")
        assert len(results) == 1

    def test_search_no_results(self, api: RegistryAPI) -> None:
        api.create("test", "prompt", [], [])
        assert api.search("zzzzz") == []


class TestClone:
    def test_clone_sets_parent_id(self, api: RegistryAPI) -> None:
        original = api.create("researcher", "prompt", ["tool"], ["perm"])
        clone = api.clone(original.id, {"name": "deep-researcher"})
        assert clone.parent_id == original.id
        assert clone.name == "deep-researcher"
        assert clone.id != original.id

    def test_clone_preserves_fields(self, api: RegistryAPI) -> None:
        original = api.create("researcher", "You research.", ["web"], ["read"])
        clone = api.clone(original.id, {"name": "clone"})
        assert clone.system_prompt == original.system_prompt
        assert clone.tools == original.tools
        assert clone.permissions == original.permissions

    def test_clone_overrides_prompt(self, api: RegistryAPI) -> None:
        original = api.create("agent", "old prompt", [], [])
        clone = api.clone(original.id, {"name": "new", "system_prompt": "new prompt"})
        assert clone.system_prompt == "new prompt"

    def test_clone_missing_raises(self, api: RegistryAPI) -> None:
        with pytest.raises(RegistryError, match="not found"):
            api.clone("nonexistent", {"name": "x"})

    def test_provenance_chain(self, api: RegistryAPI) -> None:
        a = api.create("gen-0", "p", [], [])
        b = api.clone(a.id, {"name": "gen-1"})
        c = api.clone(b.id, {"name": "gen-2"})
        assert c.parent_id == b.id
        assert b.parent_id == a.id


class TestRemove:
    def test_remove_existing(self, api: RegistryAPI) -> None:
        d = api.create("test", "p", [], [])
        assert api.remove(d.id) is True
        assert api.get(d.id) is None

    def test_remove_missing(self, api: RegistryAPI) -> None:
        assert api.remove("nonexistent") is False


class TestResolveAgent:
    def test_resolve_by_id(self, api: RegistryAPI) -> None:
        d = api.create("researcher", "prompt", [], [])
        found = api.resolve_agent(d.id)
        assert found.id == d.id

    def test_resolve_by_exact_name(self, api: RegistryAPI) -> None:
        d = api.create("researcher", "prompt", [], [])
        found = api.resolve_agent("researcher")
        assert found.id == d.id

    def test_resolve_by_substring_unique(self, api: RegistryAPI) -> None:
        d = api.create("code-reviewer", "prompt", [], [])
        found = api.resolve_agent("code-review")
        assert found.id == d.id

    def test_resolve_ambiguous_raises(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "prompt", [], [])
        api.create("code-reviewer-v2", "prompt", [], [])
        with pytest.raises(RegistryError, match="Ambiguous"):
            api.resolve_agent("code-review")

    def test_resolve_not_found_raises(self, api: RegistryAPI) -> None:
        with pytest.raises(RegistryError, match="not found"):
            api.resolve_agent("nonexistent")

    def test_resolve_exact_name_wins_over_substring(self, api: RegistryAPI) -> None:
        a = api.create("code-reviewer", "prompt", [], [])
        api.create("code-reviewer-v2", "prompt", [], [])
        found = api.resolve_agent("code-reviewer")
        assert found.id == a.id


class TestInspect:
    def test_inspect_returns_details(self, api: RegistryAPI) -> None:
        d = api.create("test", "prompt", ["tool"], ["perm"])
        info = api.inspect(d.id)
        assert info["name"] == "test"
        assert info["provenance_chain"] == []

    def test_inspect_provenance_chain(self, api: RegistryAPI) -> None:
        a = api.create("gen-0", "p", [], [])
        b = api.clone(a.id, {"name": "gen-1"})
        c = api.clone(b.id, {"name": "gen-2"})
        info = api.inspect(c.id)
        chain = info["provenance_chain"]
        assert len(chain) == 2
        assert chain[0]["name"] == "gen-1"
        assert chain[1]["name"] == "gen-0"

    def test_inspect_missing_raises(self, api: RegistryAPI) -> None:
        with pytest.raises(RegistryError, match="not found"):
            api.inspect("nonexistent")
