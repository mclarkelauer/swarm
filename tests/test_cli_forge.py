"""Tests for swarm.cli.forge_cmd."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swarm.cli.forge_cmd import _normalize, _parse_definition
from swarm.cli.main import cli
from swarm.config import SwarmConfig
from swarm.dirs import ensure_base_dir


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def _mock_config(tmp_path: Path):  # type: ignore[no-untyped-def]
    config = SwarmConfig(base_dir=tmp_path / ".swarm")
    ensure_base_dir(config.base_dir)
    with (
        patch("swarm.cli.forge_cmd.load_config", return_value=config),
        patch("swarm.cli.registry_cmd.load_config", return_value=config),
    ):
        yield config


# ---------------------------------------------------------------------------
# Parse / normalize helpers
# ---------------------------------------------------------------------------


class TestParseDefinition:
    def test_clean_json(self) -> None:
        raw = json.dumps({"name": "reviewer", "system_prompt": "Reviews.", "tools": ["Read"]})
        result = _parse_definition(raw)
        assert result is not None
        assert result["name"] == "reviewer"

    def test_json_wrapped_in_result(self) -> None:
        inner = {"name": "writer", "system_prompt": "Writes.", "tools": []}
        raw = json.dumps({"type": "result", "result": inner})
        result = _parse_definition(raw)
        assert result is not None
        assert result["name"] == "writer"

    def test_json_in_markdown_fence(self) -> None:
        raw = 'Here is the definition:\n```json\n{"name": "tester", "system_prompt": "Tests."}\n```'
        result = _parse_definition(raw)
        assert result is not None
        assert result["name"] == "tester"

    def test_plain_text_returns_none(self) -> None:
        assert _parse_definition("I can't create that agent.") is None

    def test_result_string_inner(self) -> None:
        inner_json = json.dumps({"name": "inner", "system_prompt": "p"})
        raw = json.dumps({"type": "result", "result": inner_json})
        result = _parse_definition(raw)
        assert result is not None
        assert result["name"] == "inner"


class TestNormalize:
    def test_normalizes_types(self) -> None:
        result = _normalize({"name": "x", "system_prompt": "p", "tools": ["a"], "permissions": ["b"]})
        assert result["name"] == "x"
        assert result["tools"] == ["a"]
        assert result["permissions"] == ["b"]

    def test_missing_fields_default(self) -> None:
        result = _normalize({"name": "x"})
        assert result["system_prompt"] == ""
        assert result["tools"] == []
        assert result["permissions"] == []


# ---------------------------------------------------------------------------
# forge suggest
# ---------------------------------------------------------------------------


class TestForgeSuggest:
    @pytest.mark.usefixtures("_mock_config")
    def test_no_results(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["forge", "suggest", "zzzzz"])
        assert result.exit_code == 0
        assert "No agents" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_with_results(self, runner: CliRunner) -> None:
        # Create an agent first
        runner.invoke(cli, ["registry", "create", "--name", "code-reviewer", "--prompt", "Reviews code."])
        result = runner.invoke(cli, ["forge", "suggest", "review"])
        assert result.exit_code == 0
        assert "code-reviewer" in result.output


# ---------------------------------------------------------------------------
# forge design
# ---------------------------------------------------------------------------


class TestForgeDesign:
    @pytest.mark.usefixtures("_mock_config")
    def test_design_registers_agent(self, runner: CliRunner) -> None:
        agent_json = json.dumps({
            "name": "security-scanner",
            "system_prompt": "You scan code for security vulnerabilities.",
            "tools": ["Read", "Grep"],
            "permissions": ["read"],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = agent_json
        mock_result.stderr = ""

        with patch("swarm.cli.forge_cmd.subprocess.run", return_value=mock_result):
            result = runner.invoke(cli, ["forge", "design", "scan code for security issues"])

        assert result.exit_code == 0
        assert "security-scanner" in result.output
        assert "Registered" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_design_with_name_override(self, runner: CliRunner) -> None:
        agent_json = json.dumps({
            "name": "generic",
            "system_prompt": "Does stuff.",
            "tools": [],
            "permissions": [],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = agent_json
        mock_result.stderr = ""

        with patch("swarm.cli.forge_cmd.subprocess.run", return_value=mock_result):
            result = runner.invoke(cli, ["forge", "design", "do stuff", "--name", "my-agent"])

        assert result.exit_code == 0
        assert "my-agent" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_design_dry_run(self, runner: CliRunner) -> None:
        agent_json = json.dumps({
            "name": "dry-agent",
            "system_prompt": "Does nothing.",
            "tools": [],
            "permissions": [],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = agent_json
        mock_result.stderr = ""

        with patch("swarm.cli.forge_cmd.subprocess.run", return_value=mock_result):
            result = runner.invoke(cli, ["forge", "design", "nothing", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "Registered" not in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_design_claude_not_found(self, runner: CliRunner) -> None:
        with patch("swarm.cli.forge_cmd.shutil.which", return_value=None):
            result = runner.invoke(cli, ["forge", "design", "something"])
        assert result.exit_code != 0
        assert "not found" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_design_bad_json(self, runner: CliRunner) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "I can't do that."
        mock_result.stderr = ""

        with patch("swarm.cli.forge_cmd.subprocess.run", return_value=mock_result):
            result = runner.invoke(cli, ["forge", "design", "bad prompt"])

        assert result.exit_code != 0
        assert "Could not parse" in result.output
