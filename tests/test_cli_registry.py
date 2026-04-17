"""Tests for swarm.cli.registry_cmd using CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.config import SwarmConfig
from swarm.dirs import ensure_base_dir


@pytest.fixture()
def runner(tmp_path: Path) -> CliRunner:
    return CliRunner()


@pytest.fixture()
def _mock_config(tmp_path: Path):
    config = SwarmConfig(base_dir=tmp_path / ".swarm")
    ensure_base_dir(config.base_dir)
    with patch("swarm.cli._helpers.load_config", return_value=config):
        yield config


class TestRegistryCreate:
    def test_create_agent(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli, ["registry", "create", "--name", "test-agent", "--prompt", "You test."]
        )
        assert result.exit_code == 0
        assert "Created agent" in result.output
        assert "test-agent" in result.output

    def test_create_with_tools(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli,
            ["registry", "create", "--name", "a", "--prompt", "p", "--tools", "bash,read"],
        )
        assert result.exit_code == 0

    def test_create_with_description_notes_status(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Happy path: --description, --notes, --status all flow through to API."""
        result = runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "rich-agent",
                "--prompt", "p",
                "--description", "A richly described agent",
                "--notes", "Lessons learned: prefer brevity",
                "--status", "draft",
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("rich-agent")
            assert defn.description == "A richly described agent"
            assert defn.notes == "Lessons learned: prefer brevity"
            assert defn.status == "draft"

    def test_create_with_repeated_tag_flags(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Tag list: repeated --tag flags accumulate."""
        result = runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "tagged",
                "--prompt", "p",
                "--tag", "python",
                "--tag", "review",
                "--tag", "qa",
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("tagged")
            assert list(defn.tags) == ["python", "review", "qa"]

    def test_create_with_csv_tags(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Tag list: comma-separated --tags flag works as alternative to repeated --tag."""
        result = runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "csv-tagged",
                "--prompt", "p",
                "--tags", "python, review,qa",
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("csv-tagged")
            assert list(defn.tags) == ["python", "review", "qa"]

    def test_create_with_combined_tag_forms(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Tag list: --tags and --tag may be combined; duplicates de-duplicated."""
        result = runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "combo-tagged",
                "--prompt", "p",
                "--tags", "python,review",
                "--tag", "qa",
                "--tag", "python",  # duplicate ignored
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("combo-tagged")
            assert list(defn.tags) == ["python", "review", "qa"]

    def test_create_rejects_invalid_status(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Status validation: Click rejects values outside the allowlist."""
        result = runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "bad-status",
                "--prompt", "p",
                "--status", "totally-bogus",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


class TestRegistryList:
    def test_list_empty(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["registry", "list"])
        assert result.exit_code == 0
        assert "No agents" in result.output

    def test_list_after_create(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "agent-a", "--prompt", "p"])
        result = runner.invoke(cli, ["registry", "list"])
        assert result.exit_code == 0
        assert "agent-a" in result.output


class TestRegistryInspect:
    def test_inspect_shows_details(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli, ["registry", "create", "--name", "inspector", "--prompt", "I inspect."]
        )
        agent_id = result.output.split("(")[1].split(")")[0]
        result = runner.invoke(cli, ["registry", "inspect", agent_id])
        assert result.exit_code == 0
        assert "inspector" in result.output
        assert "I inspect." in result.output

    def test_inspect_shows_provenance(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli, ["registry", "create", "--name", "parent", "--prompt", "parent prompt"]
        )
        parent_id = result.output.split("(")[1].split(")")[0]
        result = runner.invoke(cli, ["registry", "clone", parent_id, "--name", "child"])
        child_id = result.output.split("(")[1].split(")")[0]
        result = runner.invoke(cli, ["registry", "inspect", child_id])
        assert result.exit_code == 0
        assert "Provenance" in result.output
        assert "parent" in result.output

    def test_inspect_by_name(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "inspector", "--prompt", "p"])
        result = runner.invoke(cli, ["registry", "inspect", "inspector"])
        assert result.exit_code == 0
        assert "inspector" in result.output

    def test_inspect_invalid_id(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["registry", "inspect", "nonexistent"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestRegistryRemove:
    def test_remove_by_name(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "temp-agent", "--prompt", "p"])
        result = runner.invoke(cli, ["registry", "remove", "temp-agent"])
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_remove_nonexistent(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["registry", "remove", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestRegistryClone:
    def test_clone_by_name(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "base-agent", "--prompt", "p"])
        result = runner.invoke(
            cli, ["registry", "clone", "base-agent", "--name", "derived"]
        )
        assert result.exit_code == 0
        assert "derived" in result.output

    def test_clone_invalid_id(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["registry", "clone", "nonexistent", "--name", "x"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_clone_with_prompt_override(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli, ["registry", "create", "--name", "base", "--prompt", "original"]
        )
        agent_id = result.output.split("(")[1].split(")")[0]
        result = runner.invoke(
            cli, ["registry", "clone", agent_id, "--name", "derived", "--prompt", "overridden"]
        )
        assert result.exit_code == 0
        assert "derived" in result.output

    def test_clone_with_full_overrides(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Happy path: --description, --notes, --status, --permissions all flow through."""
        runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "src",
                "--prompt", "src prompt",
                "--description", "original",
                "--tag", "old-tag",
                "--notes", "original notes",
            ],
        )
        result = runner.invoke(
            cli,
            [
                "registry", "clone", "src",
                "--name", "dst",
                "--description", "new description",
                "--notes", "new notes",
                "--status", "deprecated",
                "--permissions", "Read,Write",
                "--tag", "new-tag",
                "--tag", "another",
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("dst")
            assert defn.description == "new description"
            assert defn.notes == "new notes"
            assert defn.status == "deprecated"
            assert list(defn.permissions) == ["Read", "Write"]
            assert list(defn.tags) == ["new-tag", "another"]

    def test_clone_with_csv_tags(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Tag list via --tags overrides original tags on clone."""
        runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "csv-src",
                "--prompt", "p",
                "--tag", "old",
            ],
        )
        result = runner.invoke(
            cli,
            [
                "registry", "clone", "csv-src",
                "--name", "csv-dst",
                "--tags", "alpha,beta",
            ],
        )
        assert result.exit_code == 0, result.output
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("csv-dst")
            assert list(defn.tags) == ["alpha", "beta"]

    def test_clone_rejects_invalid_status(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """Status validation on clone: Click rejects values outside the allowlist."""
        runner.invoke(cli, ["registry", "create", "--name", "src2", "--prompt", "p"])
        result = runner.invoke(
            cli,
            [
                "registry", "clone", "src2",
                "--name", "dst2",
                "--status", "imaginary",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid choice" in result.output.lower()

    def test_clone_without_overrides_preserves_fields(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        """No-override clone keeps original tags/notes/description, resets status to active."""
        runner.invoke(
            cli,
            [
                "registry", "create",
                "--name", "preserve-src",
                "--prompt", "p",
                "--description", "kept",
                "--notes", "kept-notes",
                "--tag", "keep-me",
                "--status", "deprecated",
            ],
        )
        result = runner.invoke(
            cli, ["registry", "clone", "preserve-src", "--name", "preserve-dst"]
        )
        assert result.exit_code == 0
        from swarm.cli._helpers import open_registry
        with open_registry() as api:
            defn = api.resolve_agent("preserve-dst")
            assert defn.description == "kept"
            assert defn.notes == "kept-notes"
            assert list(defn.tags) == ["keep-me"]
            # Standard clone behaviour: status resets to active.
            assert defn.status == "active"


class TestRegistryRoundTrip:
    def test_create_inspect_clone_remove(
        self, runner: CliRunner, _mock_config: SwarmConfig
    ) -> None:
        result = runner.invoke(
            cli, ["registry", "create", "--name", "base", "--prompt", "base prompt"]
        )
        assert result.exit_code == 0
        agent_id = result.output.split("(")[1].split(")")[0]

        result = runner.invoke(cli, ["registry", "clone", agent_id, "--name", "derived"])
        assert result.exit_code == 0
        clone_id = result.output.split("(")[1].split(")")[0]

        result = runner.invoke(cli, ["registry", "remove", clone_id])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["registry", "remove", agent_id])
        assert result.exit_code == 0


class TestRegistrySearch:
    def test_search(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "code-reviewer", "--prompt", "Reviews code"])
        result = runner.invoke(cli, ["registry", "search", "review"])
        assert result.exit_code == 0
        assert "code-reviewer" in result.output

    def test_search_no_match(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["registry", "search", "zzzzz"])
        assert result.exit_code == 0
        assert "No agents" in result.output
