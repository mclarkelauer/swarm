"""Tests for the top-level ``swarm ls`` command."""

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
    config = SwarmConfig(base_dir=tmp_path / ".swarm")
    ensure_base_dir(config.base_dir)
    with patch("swarm.cli._helpers.load_config", return_value=config):
        yield config


def _write_plan(directory: Path, version: int = 1) -> Path:
    plan = {
        "version": version,
        "goal": "Test the system",
        "steps": [
            {"id": "s1", "type": "task", "prompt": "Do something", "agent_type": "worker"}
        ],
    }
    path = directory / f"plan_v{version}.json"
    path.write_text(json.dumps(plan))
    return path


class TestLs:
    @pytest.mark.usefixtures("_mock_config")
    def test_ls_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["ls"])
        assert result.exit_code == 0
        assert "No agents or plans" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_ls_with_agents(self, runner: CliRunner) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "my-agent", "--prompt", "p"])
        result = runner.invoke(cli, ["ls"])
        assert result.exit_code == 0
        assert "my-agent" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_ls_with_plans(self, runner: CliRunner, tmp_path: Path) -> None:
        _write_plan(tmp_path)
        with patch("swarm.cli.main.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = runner.invoke(cli, ["ls"])
        assert result.exit_code == 0
        assert "Test the system" in result.output

    @pytest.mark.usefixtures("_mock_config")
    def test_ls_with_agents_and_plans(self, runner: CliRunner, tmp_path: Path) -> None:
        runner.invoke(cli, ["registry", "create", "--name", "agent-x", "--prompt", "p"])
        _write_plan(tmp_path)
        with patch("swarm.cli.main.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = runner.invoke(cli, ["ls"])
        assert result.exit_code == 0
        assert "agent-x" in result.output
        assert "Test the system" in result.output
