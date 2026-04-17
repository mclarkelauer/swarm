"""Tests for swarm.cli.experiment_cmd using CliRunner."""

from __future__ import annotations

from collections.abc import Iterator
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
def _mock_config(tmp_path: Path) -> Iterator[SwarmConfig]:
    config = SwarmConfig(base_dir=tmp_path / ".swarm")
    ensure_base_dir(config.base_dir)
    with patch("swarm.cli._helpers.load_config", return_value=config):
        yield config


class TestExperimentCreate:
    def test_create(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(
            cli,
            [
                "experiment", "create",
                "--name", "exp1",
                "--agent-a", "agent-v1",
                "--agent-b", "agent-v2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Created experiment" in result.output
        assert "exp1" in result.output

    def test_create_with_traffic_and_description(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "experiment", "create",
                "--name", "exp2",
                "--agent-a", "a",
                "--agent-b", "b",
                "--traffic-pct", "30",
                "--description", "speed test",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "exp2" in result.output

    def test_create_duplicate_name_errors(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "dup", "--agent-a", "a", "--agent-b", "b"],
        )
        result = runner.invoke(
            cli,
            ["experiment", "create", "--name", "dup", "--agent-a", "c", "--agent-b", "d"],
        )
        assert result.exit_code == 1
        assert "Error" in result.output


class TestExperimentList:
    def test_list_empty(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["experiment", "list"])
        assert result.exit_code == 0
        assert "No experiments" in result.output

    def test_list_after_create(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            [
                "experiment", "create",
                "--name", "exp-a",
                "--agent-a", "v1",
                "--agent-b", "v2",
            ],
        )
        result = runner.invoke(cli, ["experiment", "list"])
        assert result.exit_code == 0
        assert "exp-a" in result.output
        assert "v1" in result.output
        assert "v2" in result.output

    def test_list_filters_by_status(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "active1", "--agent-a", "a", "--agent-b", "b"],
        )
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "ended1", "--agent-a", "a", "--agent-b", "b"],
        )
        runner.invoke(cli, ["experiment", "end", "ended1"])

        result = runner.invoke(cli, ["experiment", "list", "--status", "active"])
        assert result.exit_code == 0
        assert "active1" in result.output
        assert "ended1" not in result.output

        result = runner.invoke(cli, ["experiment", "list", "--status", "ended"])
        assert result.exit_code == 0
        assert "ended1" in result.output
        assert "active1" not in result.output


class TestExperimentRecord:
    def test_record_success(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "rec1", "--agent-a", "a", "--agent-b", "b"],
        )
        result = runner.invoke(
            cli,
            [
                "experiment", "record", "rec1",
                "--variant", "A",
                "--success",
                "--duration-secs", "1.25",
                "--tokens-used", "200",
                "--cost-usd", "0.01",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Recorded A result" in result.output
        assert "success" in result.output

    def test_record_failure_flag(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "rec2", "--agent-a", "a", "--agent-b", "b"],
        )
        result = runner.invoke(
            cli,
            ["experiment", "record", "rec2", "--variant", "B", "--failure"],
        )
        assert result.exit_code == 0, result.output
        assert "failure" in result.output

    def test_record_unknown_experiment_errors(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        result = runner.invoke(
            cli, ["experiment", "record", "nonexistent", "--variant", "A"],
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_record_invalid_variant(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "rec3", "--agent-a", "a", "--agent-b", "b"],
        )
        result = runner.invoke(
            cli, ["experiment", "record", "rec3", "--variant", "C"],
        )
        # Click's choice validation rejects this with exit code 2
        assert result.exit_code != 0


class TestExperimentResults:
    def test_results_after_records(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "res1", "--agent-a", "a-v1", "--agent-b", "b-v1"],
        )
        runner.invoke(cli, ["experiment", "record", "res1", "--variant", "A", "--success"])
        runner.invoke(cli, ["experiment", "record", "res1", "--variant", "A", "--failure"])
        runner.invoke(cli, ["experiment", "record", "res1", "--variant", "B", "--success"])
        runner.invoke(cli, ["experiment", "record", "res1", "--variant", "B", "--success"])

        result = runner.invoke(cli, ["experiment", "results", "res1"])
        assert result.exit_code == 0, result.output
        assert "res1" in result.output
        assert "a-v1" in result.output
        assert "b-v1" in result.output
        # B has 2/2 successes vs A's 1/2 — winner should be B
        assert "Winner" in result.output

    def test_results_unknown_experiment(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        result = runner.invoke(cli, ["experiment", "results", "nonexistent"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestExperimentEnd:
    def test_end(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        runner.invoke(
            cli,
            ["experiment", "create", "--name", "to-end", "--agent-a", "a", "--agent-b", "b"],
        )
        result = runner.invoke(cli, ["experiment", "end", "to-end"])
        assert result.exit_code == 0
        assert "Ended experiment" in result.output

    def test_end_unknown(self, runner: CliRunner, _mock_config: SwarmConfig) -> None:
        result = runner.invoke(cli, ["experiment", "end", "nonexistent"])
        assert result.exit_code == 1
        assert "No active experiment" in result.output


class TestExperimentAssign:
    def test_assign_returns_variant_and_agent(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        runner.invoke(
            cli,
            [
                "experiment", "create",
                "--name", "asg",
                "--agent-a", "agent-a-name",
                "--agent-b", "agent-b-name",
            ],
        )
        result = runner.invoke(cli, ["experiment", "assign", "asg"])
        assert result.exit_code == 0, result.output
        # Output is "<variant>\t<agent>"
        line = result.output.strip()
        assert "\t" in line
        variant, agent = line.split("\t", 1)
        assert variant in ("A", "B")
        assert agent in ("agent-a-name", "agent-b-name")
        if variant == "A":
            assert agent == "agent-a-name"
        else:
            assert agent == "agent-b-name"

    def test_assign_unknown_experiment_errors(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        result = runner.invoke(cli, ["experiment", "assign", "nonexistent"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_assign_visible_in_help(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        result = runner.invoke(cli, ["experiment", "--help"])
        assert result.exit_code == 0
        assert "assign" in result.output


class TestExperimentRoundTrip:
    def test_create_record_results_end(
        self, runner: CliRunner, _mock_config: SwarmConfig,
    ) -> None:
        # Create
        result = runner.invoke(
            cli,
            ["experiment", "create", "--name", "rt", "--agent-a", "a", "--agent-b", "b"],
        )
        assert result.exit_code == 0

        # Record a couple of results
        runner.invoke(cli, ["experiment", "record", "rt", "--variant", "A", "--success"])
        runner.invoke(cli, ["experiment", "record", "rt", "--variant", "B", "--success"])

        # Inspect
        result = runner.invoke(cli, ["experiment", "results", "rt"])
        assert result.exit_code == 0
        assert "rt" in result.output

        # End
        result = runner.invoke(cli, ["experiment", "end", "rt"])
        assert result.exit_code == 0

        # Listing should now show it as ended
        result = runner.invoke(cli, ["experiment", "list", "--status", "ended"])
        assert "rt" in result.output
