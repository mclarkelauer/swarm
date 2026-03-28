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
