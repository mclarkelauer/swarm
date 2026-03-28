"""Tests for swarm.cli.forge_cmd."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        patch("swarm.cli._helpers.load_config", return_value=config),
        patch("swarm.cli.forge_cmd.load_config", return_value=config),
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


def _mock_spinner(stdout: str, returncode: int = 0):  # type: ignore[no-untyped-def]
    """Return a patch that replaces _run_with_spinner with a fake result."""
    fake = SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return patch("swarm.cli.forge_cmd._run_with_spinner", return_value=fake)


class TestForgeDesign:
    @pytest.mark.usefixtures("_mock_config")
    def test_design_registers_agent(self, runner: CliRunner) -> None:
        agent_json = json.dumps({
            "name": "security-scanner",
            "system_prompt": "You scan code for security vulnerabilities.",
            "tools": ["Read", "Grep"],
            "permissions": ["read"],
        })
        with _mock_spinner(agent_json):
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
        with _mock_spinner(agent_json):
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
        with _mock_spinner(agent_json):
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
        with _mock_spinner("I can't do that."):
            result = runner.invoke(cli, ["forge", "design", "bad prompt"])

        assert result.exit_code != 0
        assert "Could not parse" in result.output


class TestForgeEdit:
    @pytest.mark.usefixtures("_mock_config")
    def test_edit_creates_clone(self, runner: CliRunner) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "my-agent", "--prompt", "old prompt"])
        with patch("swarm.cli.forge_cmd.click.edit", return_value="new prompt"):
            result = runner.invoke(cli, ["forge", "edit", "my-agent"])
        assert result.exit_code == 0
        assert "Updated" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_edit_no_changes(self, runner: CliRunner) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "my-agent", "--prompt", "same prompt"])
        with patch("swarm.cli.forge_cmd.click.edit", return_value=None):
            result = runner.invoke(cli, ["forge", "edit", "my-agent"])
        assert result.exit_code == 0
        assert "No changes" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_edit_not_found(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["forge", "edit", "nonexistent"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestForgeExport:
    @pytest.mark.usefixtures("_mock_config")
    def test_export_creates_file(self, runner: CliRunner, tmp_path: Path) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "exp-agent", "--prompt", "prompt"])
        out = tmp_path / "out.agent.json"
        result = runner.invoke(cli, ["forge", "export", "exp-agent", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["name"] == "exp-agent"
        assert data["system_prompt"] == "prompt"

    @pytest.mark.usefixtures("_mock_config")
    def test_export_excludes_metadata(self, runner: CliRunner, tmp_path: Path) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "exp-agent", "--prompt", "p"])
        out = tmp_path / "out.agent.json"
        runner.invoke(cli, ["forge", "export", "exp-agent", "-o", str(out)])
        data = json.loads(out.read_text())
        assert "id" not in data
        assert "created_at" not in data
        assert "source" not in data

    @pytest.mark.usefixtures("_mock_config")
    def test_export_not_found(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["forge", "export", "nonexistent"])
        assert result.exit_code != 0


class TestForgeImport:
    @pytest.mark.usefixtures("_mock_config")
    def test_import_creates_agent(self, runner: CliRunner, tmp_path: Path) -> None:
        agent_file = tmp_path / "test.agent.json"
        agent_file.write_text(json.dumps({
            "name": "imported-agent",
            "system_prompt": "I was imported.",
            "tools": ["Read"],
            "permissions": [],
        }))
        result = runner.invoke(cli, ["forge", "import", str(agent_file)])
        assert result.exit_code == 0
        assert "Imported" in result.output
        assert "imported-agent" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_import_missing_name_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        agent_file = tmp_path / "bad.agent.json"
        agent_file.write_text(json.dumps({"system_prompt": "no name"}))
        result = runner.invoke(cli, ["forge", "import", str(agent_file)])
        assert result.exit_code != 0
