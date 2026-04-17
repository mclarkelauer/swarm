"""Tests for swarm.registry.api: RegistryAPI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.errors import RegistryError
from swarm.registry.api import RegistryAPI


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[RegistryAPI]:
    api = RegistryAPI(tmp_path / "registry.db")
    try:
        yield api
    finally:
        api.close()


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


class TestDescriptionAndTags:
    def test_create_with_description_and_tags(self, api: RegistryAPI) -> None:
        d = api.create(
            "py-reviewer",
            "Reviews Python code.",
            [],
            [],
            description="Reviews Python code",
            tags=["python", "review"],
        )
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.description == "Reviews Python code"
        assert retrieved.tags == ("python", "review")

    def test_clone_preserves_description_and_tags(self, api: RegistryAPI) -> None:
        original = api.create(
            "base-agent",
            "Base prompt.",
            [],
            [],
            description="Base description",
            tags=["base", "tag"],
        )
        clone = api.clone(original.id, {"name": "clone-agent"})
        assert clone.description == "Base description"
        assert clone.tags == ("base", "tag")

    def test_clone_overrides_description_and_tags(self, api: RegistryAPI) -> None:
        original = api.create(
            "base-agent",
            "Base prompt.",
            [],
            [],
            description="Original description",
            tags=["original"],
        )
        clone = api.clone(
            original.id,
            {
                "name": "clone-agent",
                "description": "Overridden description",
                "tags": ["new", "tags"],
            },
        )
        assert clone.description == "Overridden description"
        assert clone.tags == ("new", "tags")

    def test_search_matches_description(self, api: RegistryAPI) -> None:
        api.create(
            "schema-auditor",
            "Audits things.",
            [],
            [],
            description="database schema auditor",
        )
        api.create("unrelated", "Does something else.", [], [])
        results = api.search("database")
        assert len(results) == 1
        assert results[0].name == "schema-auditor"

    def test_search_matches_tags(self, api: RegistryAPI) -> None:
        api.create(
            "sec-auditor",
            "Audits security.",
            [],
            [],
            tags=["security", "audit"],
        )
        api.create("writer", "Writes docs.", [], [])
        results = api.search("security")
        assert len(results) == 1
        assert results[0].name == "sec-auditor"

    def test_create_without_description_tags_uses_defaults(self, api: RegistryAPI) -> None:
        d = api.create("minimal-agent", "Does stuff.", [], [])
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.description == ""
        assert retrieved.tags == ()


class TestPerformanceMetadata:
    def test_create_with_notes(self, api: RegistryAPI) -> None:
        d = api.create("agent-with-notes", "Does stuff.", [], [], notes="Learned: needs retries")
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.notes == "Learned: needs retries"

    def test_create_defaults_zero_counts_and_empty_strings(self, api: RegistryAPI) -> None:
        d = api.create("bare", "prompt", [], [])
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.usage_count == 0
        assert retrieved.failure_count == 0
        assert retrieved.last_used == ""
        assert retrieved.notes == ""

    def test_to_dict_includes_performance_fields(self, api: RegistryAPI) -> None:
        d = api.create("agent", "prompt", [], [], notes="some notes")
        data = d.to_dict()
        assert "usage_count" in data
        assert "failure_count" in data
        assert "last_used" in data
        assert "notes" in data
        assert data["usage_count"] == 0
        assert data["failure_count"] == 0
        assert data["notes"] == "some notes"

    def test_from_dict_roundtrip_with_performance_fields(self, api: RegistryAPI) -> None:
        d = api.create("agent", "prompt", [], [], notes="roundtrip note")
        data = d.to_dict()
        restored = d.from_dict(data)
        assert restored.usage_count == 0
        assert restored.failure_count == 0
        assert restored.last_used == ""
        assert restored.notes == "roundtrip note"

    def test_from_dict_backward_compat_missing_fields(self) -> None:
        """from_dict must work on old dicts that lack the new fields."""
        from swarm.registry.models import AgentDefinition
        old_dict = {
            "id": "old-id",
            "name": "old-agent",
            "system_prompt": "old prompt",
        }
        defn = AgentDefinition.from_dict(old_dict)
        assert defn.usage_count == 0
        assert defn.failure_count == 0
        assert defn.last_used == ""
        assert defn.notes == ""

    def test_clone_resets_counts_preserves_notes(self, api: RegistryAPI) -> None:
        original = api.create(
            "original", "prompt", [], [],
            notes="important lesson from production"
        )
        clone = api.clone(original.id, {"name": "cloned"})
        assert clone.usage_count == 0
        assert clone.failure_count == 0
        assert clone.last_used == ""
        assert clone.notes == "important lesson from production"

    def test_clone_notes_can_be_overridden(self, api: RegistryAPI) -> None:
        original = api.create("original", "prompt", [], [], notes="old lesson")
        clone = api.clone(original.id, {"name": "cloned", "notes": "new lesson"})
        assert clone.notes == "new lesson"

    def test_clone_resets_counts_even_when_original_had_counts(self, api: RegistryAPI) -> None:
        """Even if the original had non-zero counts (future feature), clone starts fresh."""
        original = api.create("original", "prompt", [], [])
        # Directly update the DB to simulate non-zero counts on the original
        api._conn.execute(
            "UPDATE agents SET usage_count=50, failure_count=5 WHERE id=?",
            (original.id,),
        )
        api._conn.commit()
        clone = api.clone(original.id, {"name": "derived"})
        assert clone.usage_count == 0
        assert clone.failure_count == 0

    def test_search_still_works_with_new_columns(self, api: RegistryAPI) -> None:
        api.create("searcher", "Handles searching.", [], [], notes="tested in prod")
        api.create("writer", "Writes documents.", [], [])
        results = api.search("search")
        assert len(results) == 1
        assert results[0].name == "searcher"


class TestStatus:
    def test_create_default_status_active(self, api: RegistryAPI) -> None:
        d = api.create("agent", "prompt", [], [])
        assert d.status == "active"
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.status == "active"

    def test_create_with_status_draft(self, api: RegistryAPI) -> None:
        d = api.create("draft-agent", "prompt", [], [], status="draft")
        assert d.status == "draft"
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.status == "draft"

    def test_clone_defaults_status_to_active(self, api: RegistryAPI) -> None:
        original = api.create("original", "prompt", [], [], status="deprecated")
        clone = api.clone(original.id, {"name": "cloned"})
        assert clone.status == "active"

    def test_to_dict_includes_status(self, api: RegistryAPI) -> None:
        d = api.create("agent", "prompt", [], [], status="archived")
        data = d.to_dict()
        assert "status" in data
        assert data["status"] == "archived"

    def test_from_dict_roundtrip_with_status(self) -> None:
        from swarm.registry.models import AgentDefinition

        data = {
            "id": "test-id",
            "name": "test-agent",
            "system_prompt": "prompt",
            "status": "deprecated",
        }
        defn = AgentDefinition.from_dict(data)
        assert defn.status == "deprecated"
        roundtripped = defn.to_dict()
        assert roundtripped["status"] == "deprecated"

    def test_from_dict_backward_compat_missing_status(self) -> None:
        """from_dict must default to 'active' when status is absent."""
        from swarm.registry.models import AgentDefinition

        old_dict = {
            "id": "old-id",
            "name": "old-agent",
            "system_prompt": "old prompt",
        }
        defn = AgentDefinition.from_dict(old_dict)
        assert defn.status == "active"


class TestVersion:
    def test_create_default_version_is_one(self, api: RegistryAPI) -> None:
        d = api.create("agent", "prompt", [], [])
        assert d.version == 1
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.version == 1

    def test_clone_increments_version(self, api: RegistryAPI) -> None:
        original = api.create("agent", "prompt", [], [])
        assert original.version == 1
        clone = api.clone(original.id, {"name": "agent-v2"})
        assert clone.version == 2
        clone2 = api.clone(clone.id, {"name": "agent-v3"})
        assert clone2.version == 3

    def test_clone_version_override(self, api: RegistryAPI) -> None:
        original = api.create("agent", "prompt", [], [])
        clone = api.clone(original.id, {"name": "agent-v10", "version": 10})
        assert clone.version == 10

    def test_version_in_select_cols(self, api: RegistryAPI) -> None:
        """Verify version survives a create -> get roundtrip through the DB."""
        d = api.create("agent", "prompt", [], [], version=5)
        retrieved = api.get(d.id)
        assert retrieved is not None
        assert retrieved.version == 5
        # Also verify to_dict / from_dict roundtrip
        data = retrieved.to_dict()
        assert data["version"] == 5
        from swarm.registry.models import AgentDefinition
        restored = AgentDefinition.from_dict(data)
        assert restored.version == 5


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
