"""Tests for swarm.cli.catalog_cmd — catalog list/search/show/seed commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from swarm.catalog.seed import _catalog_id
from swarm.cli.main import cli
from swarm.config import SwarmConfig
from swarm.dirs import ensure_base_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def _mock_config(tmp_path: Path):  # type: ignore[no-untyped-def]
    config = SwarmConfig(base_dir=tmp_path / ".swarm")
    ensure_base_dir(config.base_dir)
    with patch("swarm.cli._helpers.load_config", return_value=config):
        yield config


_FAKE_CATALOG: list[dict[str, object]] = [
    {
        "name": "code-researcher",
        "description": "Explores codebases and traces dependencies.",
        "tags": ["base", "technical", "research"],
        "tools": ["Read", "Grep"],
        "permissions": [],
        "notes": "Specialize with target repo layout.",
        "system_prompt": "You are a code researcher. Read code carefully.",
        "model": "sonnet",
    },
    {
        "name": "strategic-planner",
        "description": "Converts goals into structured roadmaps.",
        "tags": ["base", "general", "planning", "strategy"],
        "tools": ["Read", "Write"],
        "permissions": [],
        "notes": "Provide fiscal year structure.",
        "system_prompt": "You are a strategic planning specialist.",
        "model": "opus",
    },
    {
        "name": "business-plan-writer",
        "description": "Writes comprehensive business plans.",
        "tags": ["base", "business", "startup", "finance"],
        "tools": ["Read", "Write", "WebSearch"],
        "permissions": [],
        "notes": "Inject market data before running.",
        "system_prompt": "You are a business plan writer.",
        "model": "opus",
    },
]


def _with_fake_catalog(fn):  # type: ignore[no-untyped-def]
    """Decorator: patch catalog.seed and catalog.__init__ with _FAKE_CATALOG."""
    return patch("swarm.catalog.seed.ALL_BASE_AGENTS", _FAKE_CATALOG)(
        patch("swarm.cli.catalog_cmd.ALL_BASE_AGENTS", _FAKE_CATALOG)(fn)
    )


# ---------------------------------------------------------------------------
# swarm catalog list
# ---------------------------------------------------------------------------


class TestCatalogList:
    @_with_fake_catalog
    def test_shows_agent_names(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["catalog", "list"])
        assert result.exit_code == 0
        assert "code-researcher" in result.output
        assert "strategic-planner" in result.output
        assert "business-plan-writer" in result.output

    @_with_fake_catalog
    def test_shows_domain_headers(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["catalog", "list"])
        assert result.exit_code == 0
        assert "Technical" in result.output
        assert "General" in result.output
        assert "Business" in result.output

    @_with_fake_catalog
    def test_shows_description_text(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["catalog", "list"])
        assert result.exit_code == 0
        assert "Explores codebases" in result.output

    @_with_fake_catalog
    def test_no_subcommand_defaults_to_list(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog"])
        assert result.exit_code == 0
        assert "code-researcher" in result.output

    def test_real_catalog_list_exits_zero(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "list"])
        assert result.exit_code == 0
        # Spot-check a known agent from the real catalog
        assert "code-researcher" in result.output

    def test_real_catalog_shows_all_three_domains(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "list"])
        assert result.exit_code == 0
        assert "Technical" in result.output
        assert "General" in result.output
        assert "Business" in result.output


# ---------------------------------------------------------------------------
# swarm catalog search
# ---------------------------------------------------------------------------


class TestCatalogSearch:
    @_with_fake_catalog
    def test_finds_by_name_substring(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "researcher"])
        assert result.exit_code == 0
        assert "code-researcher" in result.output
        assert "strategic-planner" not in result.output

    @_with_fake_catalog
    def test_finds_by_description_substring(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "roadmaps"])
        assert result.exit_code == 0
        assert "strategic-planner" in result.output

    @_with_fake_catalog
    def test_finds_by_tag(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "startup"])
        assert result.exit_code == 0
        assert "business-plan-writer" in result.output

    @_with_fake_catalog
    def test_case_insensitive(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "RESEARCH"])
        assert result.exit_code == 0
        assert "code-researcher" in result.output

    @_with_fake_catalog
    def test_no_match_reports_clearly(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "zzz-nonexistent-zzz"])
        assert result.exit_code == 0
        assert "No base agents" in result.output

    @_with_fake_catalog
    def test_shows_match_count(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "base"])
        assert result.exit_code == 0
        # "base" appears in every agent's tags, so all 3 match
        assert "3 found" in result.output

    def test_real_catalog_search_exits_zero(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "search", "code"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# swarm catalog show
# ---------------------------------------------------------------------------


class TestCatalogShow:
    @_with_fake_catalog
    def test_shows_system_prompt(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "You are a code researcher" in result.output

    @_with_fake_catalog
    def test_shows_description(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "Explores codebases" in result.output

    @_with_fake_catalog
    def test_shows_tools(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "Read" in result.output
        assert "Grep" in result.output

    @_with_fake_catalog
    def test_shows_specialization_notes(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "Specialize with target repo layout" in result.output

    @_with_fake_catalog
    def test_shows_catalog_id(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        expected_prefix = _catalog_id("code-researcher")[:12]
        assert expected_prefix in result.output

    @_with_fake_catalog
    def test_shows_model(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "sonnet" in result.output

    @_with_fake_catalog
    def test_unknown_agent_exits_nonzero(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "does-not-exist"])
        assert result.exit_code != 0
        assert "No catalog agent" in result.output

    @_with_fake_catalog
    def test_registry_status_not_in_registry(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        # Registry is empty — should say agent is not yet seeded.
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_real_catalog_show_exits_zero(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "show", "code-researcher"])
        assert result.exit_code == 0
        assert "code-researcher" in result.output


# ---------------------------------------------------------------------------
# swarm catalog seed
# ---------------------------------------------------------------------------


class TestCatalogSeed:
    @_with_fake_catalog
    def test_seed_creates_agents(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "seed"])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert "3" in result.output  # 3 fake agents

    @_with_fake_catalog
    def test_seed_idempotent(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        runner.invoke(cli, ["catalog", "seed"])
        result = runner.invoke(cli, ["catalog", "seed"])
        assert result.exit_code == 0
        # Second run — nothing created
        assert "unchanged" in result.output.lower() or "up to date" in result.output.lower()

    @_with_fake_catalog
    def test_seed_quiet_flag_suppresses_unchanged(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        runner.invoke(cli, ["catalog", "seed"])
        result = runner.invoke(cli, ["catalog", "seed", "--quiet"])
        assert result.exit_code == 0
        # With -q and no changes, there should be minimal output
        assert "Created" not in result.output

    def test_real_catalog_seed_exits_zero(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(cli, ["catalog", "seed"])
        assert result.exit_code == 0

    def test_real_catalog_seed_twice_is_idempotent(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        runner.invoke(cli, ["catalog", "seed"])
        result = runner.invoke(cli, ["catalog", "seed"])
        assert result.exit_code == 0
        assert "Created" not in result.output


# ---------------------------------------------------------------------------
# CLI group structure
# ---------------------------------------------------------------------------


class TestCatalogCommandGroup:
    def test_help_shows_subcommands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["catalog", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "search" in result.output
        assert "show" in result.output
        assert "seed" in result.output

    def test_swarm_help_includes_catalog(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "catalog" in result.output
