"""Tests for swarm.cli.mcp_cmd: mcp-config command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from swarm.cli.main import cli


class TestMcpConfig:
    def test_outputs_valid_json(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "swarm" in data

    def test_server_block_has_command(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config"])
        data = json.loads(result.output)
        assert "command" in data["swarm"]

    def test_server_block_has_env(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config"])
        data = json.loads(result.output)
        env = data["swarm"]["env"]
        assert "SWARM_BASE_DIR" in env
        assert "SWARM_PLANS_DIR" in env

    def test_json_file_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config", "--json-file"])
        data = json.loads(result.output)
        assert "mcpServers" in data
        assert "swarm" in data["mcpServers"]

    def test_custom_plans_dir(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config", "--plans-dir", "/tmp/myplans"])
        data = json.loads(result.output)
        # The CLI resolves the path; on macOS /tmp is a symlink to /private/tmp,
        # so compare against the resolved form rather than the literal input.
        assert data["swarm"]["env"]["SWARM_PLANS_DIR"] == str(Path("/tmp/myplans").resolve())
