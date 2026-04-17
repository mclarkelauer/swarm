"""Tests for swarm.forge.ranking: build_ranking_prompt and parse_ranking_response."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.forge.api import ForgeAPI
from swarm.forge.ranking import build_ranking_prompt, parse_ranking_response
from swarm.mcp import state
from swarm.mcp.forge_tools import forge_create, forge_suggest_ranked
from swarm.registry.api import RegistryAPI
from swarm.registry.models import AgentDefinition


def _make_agent(name: str, description: str = "") -> AgentDefinition:
    return AgentDefinition(
        id=name,
        name=name,
        system_prompt=f"You are the {name} agent.",
        description=description,
    )


# ---------------------------------------------------------------------------
# build_ranking_prompt
# ---------------------------------------------------------------------------


class TestBuildRankingPrompt:
    def test_includes_query(self) -> None:
        candidates = [_make_agent("code-reviewer")]
        prompt = build_ranking_prompt("review Python security", candidates)
        assert "review Python security" in prompt

    def test_includes_all_candidate_names(self) -> None:
        candidates = [
            _make_agent("code-reviewer"),
            _make_agent("doc-writer"),
            _make_agent("deployer"),
        ]
        prompt = build_ranking_prompt("deploy app", candidates)
        assert "code-reviewer" in prompt
        assert "doc-writer" in prompt
        assert "deployer" in prompt

    def test_uses_no_description_fallback_for_empty(self) -> None:
        candidates = [_make_agent("agent-a", description="")]
        prompt = build_ranking_prompt("some task", candidates)
        assert "(no description)" in prompt

    def test_uses_provided_description(self) -> None:
        candidates = [_make_agent("reviewer", description="Reviews code quality")]
        prompt = build_ranking_prompt("review", candidates)
        assert "Reviews code quality" in prompt

    def test_candidates_numbered_one_based(self) -> None:
        candidates = [
            _make_agent("alpha"),
            _make_agent("beta"),
            _make_agent("gamma"),
        ]
        prompt = build_ranking_prompt("task", candidates)
        assert "1." in prompt or "  1." in prompt
        assert "2." in prompt or "  2." in prompt
        assert "3." in prompt or "  3." in prompt

    def test_prompt_instructs_comma_separated_output(self) -> None:
        candidates = [_make_agent("a"), _make_agent("b")]
        prompt = build_ranking_prompt("task", candidates)
        # Should mention comma-separated ranking
        assert "comma" in prompt.lower() or "," in prompt

    def test_single_candidate(self) -> None:
        candidates = [_make_agent("solo-agent", description="Does everything")]
        prompt = build_ranking_prompt("complex task", candidates)
        assert "solo-agent" in prompt
        assert "Does everything" in prompt

    def test_empty_candidates_list(self) -> None:
        # Should not raise; result is valid string
        prompt = build_ranking_prompt("task", [])
        assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# parse_ranking_response
# ---------------------------------------------------------------------------


class TestParseRankingResponse:
    def _make_candidates(self, names: list[str]) -> list[AgentDefinition]:
        return [_make_agent(n) for n in names]

    def test_numbered_list_reorders_correctly(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        # LLM says gamma (3) first, then alpha (1), then beta (2)
        result = parse_ranking_response("3, 1, 2", candidates)
        assert [a.name for a in result] == ["gamma", "alpha", "beta"]

    def test_partial_ranking_appends_unmentioned(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        # Only mentions 2 and 1 — gamma (3) should be appended
        result = parse_ranking_response("2, 1", candidates)
        assert result[0].name == "beta"
        assert result[1].name == "alpha"
        assert result[2].name == "gamma"

    def test_invalid_response_returns_original_order(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        result = parse_ranking_response("I cannot rank these", candidates)
        assert [a.name for a in result] == ["alpha", "beta", "gamma"]

    def test_out_of_range_numbers_ignored(self) -> None:
        candidates = self._make_candidates(["alpha", "beta"])
        # Numbers 1-2 are valid; 99 is out of range
        result = parse_ranking_response("99, 2, 1", candidates)
        # 99 is ignored; 2 and 1 are used
        assert result[0].name == "beta"
        assert result[1].name == "alpha"

    def test_empty_candidates_returns_empty(self) -> None:
        result = parse_ranking_response("1, 2, 3", [])
        assert result == []

    def test_empty_response_returns_original_order(self) -> None:
        candidates = self._make_candidates(["alpha", "beta"])
        result = parse_ranking_response("", candidates)
        assert [a.name for a in result] == ["alpha", "beta"]

    def test_single_candidate_returned(self) -> None:
        candidates = self._make_candidates(["solo"])
        result = parse_ranking_response("1", candidates)
        assert [a.name for a in result] == ["solo"]

    def test_duplicate_numbers_deduplicated(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        # 1 appears twice — should only include alpha once
        result = parse_ranking_response("1, 1, 2", candidates)
        assert result.count(candidates[0]) == 1

    def test_all_candidates_present_in_result(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        result = parse_ranking_response("2", candidates)
        # All three should appear (unmentioned appended in order)
        assert len(result) == 3
        result_names = [a.name for a in result]
        assert "alpha" in result_names
        assert "beta" in result_names
        assert "gamma" in result_names

    def test_name_based_fallback_reorders(self) -> None:
        # Response has no numbers, but contains agent names line by line
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        response = "gamma\nalpha\nbeta"
        result = parse_ranking_response(response, candidates)
        assert result[0].name == "gamma"
        assert result[1].name == "alpha"
        assert result[2].name == "beta"

    def test_name_based_fallback_appends_unmentioned(self) -> None:
        candidates = self._make_candidates(["alpha", "beta", "gamma"])
        # Only gamma and alpha mentioned by name
        response = "gamma\nalpha"
        result = parse_ranking_response(response, candidates)
        assert result[0].name == "gamma"
        assert result[1].name == "alpha"
        assert result[2].name == "beta"


# ---------------------------------------------------------------------------
# forge_suggest_ranked MCP tool
# ---------------------------------------------------------------------------


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


class TestForgeSuggestRanked:
    def test_returns_candidates_and_ranking_prompt(self) -> None:
        forge_create("code-reviewer", "Reviews Python code for security issues.",
                     description="Security-focused code reviewer")
        # "reviewer" is a substring of both name and description
        result = json.loads(forge_suggest_ranked("reviewer"))
        assert "candidates" in result
        assert "ranking_prompt" in result
        assert len(result["candidates"]) > 0
        assert isinstance(result["ranking_prompt"], str)
        assert len(result["ranking_prompt"]) > 0

    def test_ranking_prompt_includes_query(self) -> None:
        forge_create("data-analyst", "Analyzes data thoroughly.", description="Data analyst")
        # "analyst" matches the agent name and description
        result = json.loads(forge_suggest_ranked("analyst"))
        assert "analyst" in result["ranking_prompt"]

    def test_no_matches_returns_empty(self) -> None:
        forge_create("code-reviewer", "Reviews code.")
        result = json.loads(forge_suggest_ranked("zzzzz_no_match_xyz"))
        assert result["candidates"] == []
        assert result["ranking_prompt"] == ""

    def test_candidates_have_truncated_system_prompt(self) -> None:
        long_prompt = "X" * 120
        forge_create("verbose-agent", long_prompt)
        result = json.loads(forge_suggest_ranked("verbose"))
        assert len(result["candidates"]) > 0
        for candidate in result["candidates"]:
            assert len(candidate["system_prompt"]) <= 83  # 80 chars + "..."

    def test_multiple_candidates_all_present(self) -> None:
        forge_create("reviewer", "Reviews code quality.")
        forge_create("reviewer-security", "Reviews security of code.")
        result = json.loads(forge_suggest_ranked("review"))
        names = [c["name"] for c in result["candidates"]]
        assert "reviewer" in names
        assert "reviewer-security" in names
