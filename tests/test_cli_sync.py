"""Tests for the ``swarm sync`` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from swarm.cli.main import cli
from swarm.config import SwarmConfig
from swarm.dirs import ensure_base_dir


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def _mock_config(tmp_path: Path):  # type: ignore[no-untyped-def]
    config = SwarmConfig(base_dir=tmp_path / ".swarm-home")
    ensure_base_dir(config.base_dir)
    with patch("swarm.cli._helpers.load_config", return_value=config):
        yield config


def _write_project_agent(project_dir: Path, name: str, prompt: str = "prompt") -> None:
    agents_dir = project_dir / ".swarm" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.agent.json").write_text(json.dumps({
        "name": name,
        "system_prompt": prompt,
        "tools": [],
        "permissions": [],
    }))


class TestSync:
    @pytest.mark.usefixtures("_mock_config")
    def test_sync_imports_new_agents(self, runner: CliRunner, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        _write_project_agent(project, "new-agent")
        result = runner.invoke(cli, ["sync", "--dir", str(project)])
        assert result.exit_code == 0
        assert "Imported" in result.output
        assert "1 imported" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_sync_skips_existing(self, runner: CliRunner, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        _write_project_agent(project, "existing-agent")
        # Create the agent first
        runner.invoke(
            cli, ["registry", "create", "--name", "existing-agent", "--prompt", "already here"]
        )
        result = runner.invoke(cli, ["sync", "--dir", str(project)])
        assert result.exit_code == 0
        assert "Already registered" in result.output
        assert "0 imported" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_sync_no_agents_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["sync", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No .swarm/agents/" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_sync_empty_agents_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        (tmp_path / ".swarm" / "agents").mkdir(parents=True)
        result = runner.invoke(cli, ["sync", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "0 imported" in result.output
