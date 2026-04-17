"""Tests for FTS5-based semantic search in the agent registry."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.registry_tools import registry_search_ranked
from swarm.registry.api import RegistryAPI, _sanitize_fts_query
from swarm.registry.db import _init_fts, init_registry_db


# ---------------------------------------------------------------------------
# _sanitize_fts_query
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    """Tests for the FTS5 query sanitization function."""

    def test_simple_single_word(self) -> None:
        assert _sanitize_fts_query("python") == '"python"*'

    def test_multiple_words(self) -> None:
        result = _sanitize_fts_query("python test")
        assert result == '"python"* "test"*'

    def test_hyphenated_word(self) -> None:
        # Hyphens are preserved; FTS5's tokenizer splits on them at match time
        result = _sanitize_fts_query("code-reviewer")
        assert result == '"code-reviewer"*'

    def test_strips_double_quotes(self) -> None:
        result = _sanitize_fts_query('he said "hi"')
        assert result == '"he"* "said"* "hi"*'

    def test_strips_star(self) -> None:
        result = _sanitize_fts_query("python*")
        assert result == '"python"*'

    def test_strips_caret(self) -> None:
        result = _sanitize_fts_query("^python")
        assert result == '"python"*'

    def test_strips_parens(self) -> None:
        result = _sanitize_fts_query("(python OR test)")
        assert result == '"python"* "test"*'

    def test_strips_braces(self) -> None:
        result = _sanitize_fts_query("{python}")
        assert result == '"python"*'

    def test_strips_AND(self) -> None:
        result = _sanitize_fts_query("python AND test")
        assert result == '"python"* "test"*'

    def test_strips_OR(self) -> None:
        result = _sanitize_fts_query("python OR test")
        assert result == '"python"* "test"*'

    def test_strips_NOT(self) -> None:
        result = _sanitize_fts_query("python NOT test")
        assert result == '"python"* "test"*'

    def test_strips_NEAR(self) -> None:
        result = _sanitize_fts_query("python NEAR test")
        assert result == '"python"* "test"*'

    def test_case_insensitive_operator_stripping(self) -> None:
        result = _sanitize_fts_query("python and test")
        assert result == '"python"* "test"*'

    def test_empty_query(self) -> None:
        assert _sanitize_fts_query("") == '""'

    def test_only_special_chars(self) -> None:
        assert _sanitize_fts_query('***"()') == '""'


# ---------------------------------------------------------------------------
# _init_fts
# ---------------------------------------------------------------------------


class TestInitFts:
    """Tests for the FTS5 initialization function."""

    def test_returns_true_when_fts5_available(self, tmp_path: Path) -> None:
        conn, fts_available = init_registry_db(tmp_path / "registry.db")
        try:
            # On standard Python/macOS/Linux builds, FTS5 is compiled in
            assert fts_available is True
        finally:
            conn.close()

    def test_creates_fts_virtual_table(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agents_fts'"
            )
            assert cur.fetchone() is not None
        finally:
            conn.close()

    def test_creates_sync_triggers(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
            trigger_names = {row[0] for row in cur.fetchall()}
            expected = {
                "agents_fts_insert",
                "agents_fts_update_delete",
                "agents_fts_update_insert",
                "agents_fts_delete",
            }
            assert expected.issubset(trigger_names)
        finally:
            conn.close()

    def test_idempotent_fts_init(self, tmp_path: Path) -> None:
        """Calling _init_fts multiple times does not raise."""
        conn, fts1 = init_registry_db(tmp_path / "registry.db")
        try:
            fts2 = _init_fts(conn)
            assert fts1 is True
            assert fts2 is True
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# FTS5 search via RegistryAPI
# ---------------------------------------------------------------------------


class TestFtsSearch:
    """Tests for RegistryAPI.search() using FTS5."""

    @pytest.fixture()
    def api(self, tmp_path: Path) -> Iterator[RegistryAPI]:
        api = RegistryAPI(tmp_path / "registry.db")
        try:
            yield api
        finally:
            api.close()

    def test_search_by_name(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [])
        api.create("writer", "Writes docs.", [], [])
        results = api.search("reviewer")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_name_prefix(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [])
        api.create("writer", "Writes docs.", [], [])
        results = api.search("review")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_description(self, api: RegistryAPI) -> None:
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

    def test_search_by_system_prompt(self, api: RegistryAPI) -> None:
        api.create("agent-a", "Handles security audits.", [], [])
        results = api.search("security")
        assert len(results) == 1

    def test_search_by_tags(self, api: RegistryAPI) -> None:
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

    def test_search_no_results(self, api: RegistryAPI) -> None:
        api.create("test", "prompt", [], [])
        assert api.search("zzzzz") == []

    def test_search_respects_limit(self, api: RegistryAPI) -> None:
        for i in range(10):
            api.create(f"python-agent-{i}", "Python programming agent.", [], [])
        results = api.search("python", limit=3)
        assert len(results) == 3

    def test_search_fts_available_flag(self, api: RegistryAPI) -> None:
        """Verify FTS5 is being used."""
        assert api._fts_available is True

    def test_search_after_insert_triggers_sync(self, api: RegistryAPI) -> None:
        """FTS index is auto-updated after create via trigger."""
        api.create("dynamic-agent", "Dynamically created.", [], [])
        results = api.search("dynamic")
        assert len(results) == 1

    def test_search_after_remove_triggers_sync(self, api: RegistryAPI) -> None:
        """FTS index is updated after remove via trigger."""
        defn = api.create("removable-agent", "Will be removed.", [], [])
        api.remove(defn.id)
        results = api.search("removable")
        assert results == []

    def test_search_after_clone_triggers_sync(self, api: RegistryAPI) -> None:
        """FTS index is updated after clone via trigger."""
        original = api.create("base-agent", "Base prompt.", [], [])
        api.clone(original.id, {"name": "derived-agent"})
        results = api.search("derived")
        assert len(results) == 1
        assert results[0].name == "derived-agent"

    def test_search_multiple_terms(self, api: RegistryAPI) -> None:
        api.create(
            "python-test-writer",
            "Writes pytest test suites.",
            [],
            [],
            tags=["python", "testing"],
        )
        api.create("go-writer", "Writes Go code.", [], [])
        results = api.search("python testing")
        assert len(results) == 1
        assert results[0].name == "python-test-writer"


# ---------------------------------------------------------------------------
# search_with_snippets
# ---------------------------------------------------------------------------


class TestSearchWithSnippets:
    """Tests for RegistryAPI.search_with_snippets()."""

    @pytest.fixture()
    def api(self, tmp_path: Path) -> Iterator[RegistryAPI]:
        api = RegistryAPI(tmp_path / "registry.db")
        try:
            yield api
        finally:
            api.close()

    def test_returns_dicts_with_expected_keys(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [], tags=["review"])
        results = api.search_with_snippets("reviewer")
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "name" in result
        assert "description" in result
        assert "tags" in result
        assert "rank" in result
        assert "snippets" in result

    def test_rank_is_negative_float(self, api: RegistryAPI) -> None:
        """BM25 scores are negative (lower is better)."""
        api.create("code-reviewer", "Reviews code.", [], [])
        results = api.search_with_snippets("reviewer")
        assert len(results) == 1
        assert isinstance(results[0]["rank"], float)
        assert results[0]["rank"] < 0

    def test_snippets_contain_bold_markers(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code quality.", [], [])
        results = api.search_with_snippets("reviewer")
        assert len(results) == 1
        snippets = results[0]["snippets"]
        # The name should contain <b>...</b> markers around "reviewer"
        assert isinstance(snippets, dict)
        assert any("<b>" in str(v) for v in snippets.values())

    def test_no_results(self, api: RegistryAPI) -> None:
        api.create("test", "prompt", [], [])
        results = api.search_with_snippets("zzzzz")
        assert results == []

    def test_respects_limit(self, api: RegistryAPI) -> None:
        for i in range(10):
            api.create(f"python-agent-{i}", "Python agent.", [], [])
        results = api.search_with_snippets("python", limit=3)
        assert len(results) == 3

    def test_tags_are_lists(self, api: RegistryAPI) -> None:
        api.create(
            "tagged-agent",
            "An agent with tags.",
            [],
            [],
            tags=["python", "testing"],
        )
        results = api.search_with_snippets("tagged")
        assert len(results) == 1
        assert isinstance(results[0]["tags"], list)
        assert "python" in results[0]["tags"]


# ---------------------------------------------------------------------------
# LIKE fallback (when FTS5 is unavailable)
# ---------------------------------------------------------------------------


class TestLikeFallback:
    """Tests for the _search_like fallback path."""

    @pytest.fixture()
    def api(self, tmp_path: Path) -> Iterator[RegistryAPI]:
        api = RegistryAPI(tmp_path / "registry.db")
        # Force LIKE fallback
        api._fts_available = False
        try:
            yield api
        finally:
            api.close()

    def test_search_like_by_name(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [])
        results = api.search("review")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_like_by_prompt(self, api: RegistryAPI) -> None:
        api.create("agent-a", "Handles security audits.", [], [])
        results = api.search("security")
        assert len(results) == 1

    def test_search_like_no_results(self, api: RegistryAPI) -> None:
        api.create("test", "prompt", [], [])
        assert api.search("zzzzz") == []

    def test_search_with_snippets_fallback(self, api: RegistryAPI) -> None:
        api.create("code-reviewer", "Reviews code.", [], [], tags=["review"])
        results = api.search_with_snippets("review")
        assert len(results) >= 1
        # Fallback returns rank=0.0 and empty snippets
        assert results[0]["rank"] == 0.0
        assert results[0]["snippets"] == {}


# ---------------------------------------------------------------------------
# MCP tool: registry_search_ranked
# ---------------------------------------------------------------------------


class TestRegistrySearchRankedTool:
    """Tests for the registry_search_ranked MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup_state(self, tmp_path: Path) -> Iterator[None]:
        state.registry_api = RegistryAPI(tmp_path / "registry.db")
        try:
            yield
        finally:
            assert state.registry_api is not None
            state.registry_api.close()
            state.registry_api = None

    def test_returns_json_array(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("code-reviewer", "Reviews code.", [], [])
        result = json.loads(registry_search_ranked("reviewer"))
        assert isinstance(result, list)
        assert len(result) == 1

    def test_result_has_expected_keys(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("code-reviewer", "Reviews code.", [], [])
        result = json.loads(registry_search_ranked("reviewer"))
        item = result[0]
        assert "id" in item
        assert "name" in item
        assert "description" in item
        assert "tags" in item
        assert "rank" in item
        assert "snippets" in item

    def test_respects_limit(self) -> None:
        assert state.registry_api is not None
        for i in range(10):
            state.registry_api.create(f"python-agent-{i}", "Python agent.", [], [])
        result = json.loads(registry_search_ranked("python", limit="3"))
        assert len(result) == 3

    def test_no_results(self) -> None:
        result = json.loads(registry_search_ranked("nonexistent"))
        assert result == []

    def test_snippets_present(self) -> None:
        assert state.registry_api is not None
        state.registry_api.create("code-reviewer", "Reviews code quality.", [], [])
        result = json.loads(registry_search_ranked("reviewer"))
        assert len(result) == 1
        assert isinstance(result[0]["snippets"], dict)


# ---------------------------------------------------------------------------
# BM25 ordering
# ---------------------------------------------------------------------------


class TestBm25Ordering:
    """Tests verifying BM25 ranking behavior."""

    @pytest.fixture()
    def api(self, tmp_path: Path) -> Iterator[RegistryAPI]:
        api = RegistryAPI(tmp_path / "registry.db")
        try:
            yield api
        finally:
            api.close()

    def test_name_match_ranked_higher_than_prompt_match(self, api: RegistryAPI) -> None:
        """An agent whose name contains the search term should rank higher
        than one that only mentions it in a long system prompt."""
        # Agent with 'python' in name
        api.create(
            "python-expert",
            "General programming agent.",
            [],
            [],
        )
        # Agent with 'python' only deep in a long prompt
        api.create(
            "general-agent",
            "You handle many tasks. " * 50 + "Sometimes python comes up.",
            [],
            [],
        )
        results = api.search_with_snippets("python")
        assert len(results) == 2
        # The python-expert should appear first (lower BM25 score = better)
        assert results[0]["name"] == "python-expert"

    def test_multiple_results_sorted_by_rank(self, api: RegistryAPI) -> None:
        """Results from search_with_snippets are sorted by BM25 rank."""
        api.create("python-expert", "Python programming.", [], [])
        api.create("python-beginner", "Learning python basics.", [], [])
        api.create("generic", "General purpose. " * 100 + "python", [], [])
        results = api.search_with_snippets("python")
        assert len(results) == 3
        # Ranks should be in ascending order (lower = better for BM25)
        ranks = [r["rank"] for r in results]
        assert ranks == sorted(ranks)
