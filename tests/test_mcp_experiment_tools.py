"""Tests for swarm.mcp.experiment_tools."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.experiments.api import ExperimentAPI
from swarm.mcp import state
from swarm.mcp.experiment_tools import (
    experiment_assign_variant,
    experiment_create,
    experiment_end,
    experiment_get_results,
    experiment_list,
    experiment_record_result,
)


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> Iterator[None]:
    state.experiment_api = ExperimentAPI(tmp_path / "experiments.db")
    state.plans_dir = str(tmp_path)
    try:
        yield
    finally:
        assert state.experiment_api is not None
        state.experiment_api.close()
        state.experiment_api = None


class TestExperimentCreate:
    def test_create_returns_experiment(self) -> None:
        result = json.loads(experiment_create("exp1", "agent-a", "agent-b"))
        assert result["name"] == "exp1"
        assert result["agent_a"] == "agent-a"
        assert result["agent_b"] == "agent-b"
        assert result["traffic_pct"] == 50.0
        assert result["status"] == "active"
        assert "id" in result

    def test_create_with_custom_traffic_and_description(self) -> None:
        result = json.loads(
            experiment_create(
                "exp1", "agent-a", "agent-b",
                traffic_pct="75", description="Test description",
            )
        )
        assert result["traffic_pct"] == 75.0
        assert result["description"] == "Test description"

    def test_create_missing_name(self) -> None:
        result = json.loads(experiment_create("", "a", "b"))
        assert "error" in result
        assert "name" in result["error"]

    def test_create_missing_agent_a(self) -> None:
        result = json.loads(experiment_create("exp", "", "b"))
        assert "error" in result
        assert "agent_a" in result["error"]

    def test_create_missing_agent_b(self) -> None:
        result = json.loads(experiment_create("exp", "a", ""))
        assert "error" in result
        assert "agent_b" in result["error"]

    def test_create_invalid_traffic_pct(self) -> None:
        result = json.loads(
            experiment_create("exp", "a", "b", traffic_pct="not-a-number")
        )
        assert "error" in result
        assert "traffic_pct" in result["error"]

    def test_create_duplicate_name_returns_error(self) -> None:
        experiment_create("dup", "a", "b")
        result = json.loads(experiment_create("dup", "c", "d"))
        assert "error" in result


class TestExperimentList:
    def test_list_empty(self) -> None:
        result = json.loads(experiment_list())
        assert result == []

    def test_list_returns_created_experiments(self) -> None:
        experiment_create("exp1", "a1", "b1")
        experiment_create("exp2", "a2", "b2")
        result = json.loads(experiment_list())
        names = {e["name"] for e in result}
        assert names == {"exp1", "exp2"}

    def test_list_filters_by_status(self) -> None:
        experiment_create("active-exp", "a", "b")
        experiment_create("ended-exp", "a", "b")
        experiment_end("ended-exp")
        active = json.loads(experiment_list(status="active"))
        ended = json.loads(experiment_list(status="ended"))
        assert len(active) == 1
        assert active[0]["name"] == "active-exp"
        assert len(ended) == 1
        assert ended[0]["name"] == "ended-exp"


class TestExperimentGetResults:
    def test_get_results_returns_aggregates(self) -> None:
        experiment_create("exp", "agent-a", "agent-b")
        experiment_record_result("exp", "A", success="true")
        experiment_record_result("exp", "A", success="false")
        experiment_record_result("exp", "B", success="true")

        result = json.loads(experiment_get_results("exp"))
        assert result["name"] == "exp"
        assert result["variants"]["A"]["total_runs"] == 2
        assert result["variants"]["A"]["successes"] == 1
        assert result["variants"]["B"]["total_runs"] == 1
        assert result["variants"]["B"]["successes"] == 1

    def test_get_results_missing_name(self) -> None:
        result = json.loads(experiment_get_results(""))
        assert "error" in result

    def test_get_results_unknown_experiment(self) -> None:
        result = json.loads(experiment_get_results("nonexistent"))
        assert "error" in result
        assert "not found" in result["error"]


class TestExperimentRecordResult:
    def test_record_success(self) -> None:
        experiment_create("exp", "a", "b")
        result = json.loads(
            experiment_record_result(
                "exp", "A",
                success="true", duration_secs="1.5",
                tokens_used="100", cost_usd="0.05",
                run_id="r1", step_id="s1",
            )
        )
        assert result["variant"] == "A"
        assert result["success"] is True
        assert "id" in result

    def test_record_failure(self) -> None:
        experiment_create("exp", "a", "b")
        result = json.loads(
            experiment_record_result("exp", "B", success="false")
        )
        assert result["variant"] == "B"
        assert result["success"] is False

    def test_record_missing_experiment_name(self) -> None:
        result = json.loads(experiment_record_result("", "A"))
        assert "error" in result
        assert "experiment_name" in result["error"]

    def test_record_invalid_variant(self) -> None:
        experiment_create("exp", "a", "b")
        result = json.loads(experiment_record_result("exp", "C"))
        assert "error" in result
        assert "variant" in result["error"]

    def test_record_invalid_numeric(self) -> None:
        experiment_create("exp", "a", "b")
        result = json.loads(
            experiment_record_result("exp", "A", duration_secs="not-a-float")
        )
        assert "error" in result

    def test_record_unknown_experiment(self) -> None:
        result = json.loads(experiment_record_result("nonexistent", "A"))
        assert "error" in result
        assert "not found" in result["error"]


class TestExperimentAssignVariant:
    def test_assign_returns_agent_and_variant(self) -> None:
        experiment_create("exp", "agent-a", "agent-b")
        result = json.loads(experiment_assign_variant("exp"))
        assert result["agent"] in ("agent-a", "agent-b")
        assert result["variant"] in ("A", "B")

    def test_assign_100_percent_to_b(self) -> None:
        experiment_create("exp", "agent-a", "agent-b", traffic_pct="100")
        for _ in range(10):
            result = json.loads(experiment_assign_variant("exp"))
            assert result["agent"] == "agent-b"
            assert result["variant"] == "B"

    def test_assign_missing_name(self) -> None:
        result = json.loads(experiment_assign_variant(""))
        assert "error" in result

    def test_assign_unknown_experiment(self) -> None:
        result = json.loads(experiment_assign_variant("nonexistent"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_assign_ended_experiment(self) -> None:
        experiment_create("exp", "a", "b")
        experiment_end("exp")
        result = json.loads(experiment_assign_variant("exp"))
        assert "error" in result


class TestExperimentEnd:
    def test_end_active_experiment(self) -> None:
        experiment_create("exp", "a", "b")
        result = json.loads(experiment_end("exp"))
        assert result["ok"] is True
        assert result["name"] == "exp"

    def test_end_unknown_experiment(self) -> None:
        result = json.loads(experiment_end("nonexistent"))
        assert result["ok"] is False

    def test_end_already_ended(self) -> None:
        experiment_create("exp", "a", "b")
        experiment_end("exp")
        second = json.loads(experiment_end("exp"))
        assert second["ok"] is False

    def test_end_missing_name(self) -> None:
        result = json.loads(experiment_end(""))
        assert "error" in result


class TestLazyApiResolution:
    def test_get_experiment_api_uses_state_when_set(self) -> None:
        from swarm.mcp.experiment_tools import _get_experiment_api

        api = _get_experiment_api()
        assert api is state.experiment_api

    def test_get_experiment_api_lazy_falls_back_to_plans_dir(
        self, tmp_path: Path,
    ) -> None:
        from swarm.mcp.experiment_tools import _get_experiment_api

        # Tear down the autouse fixture state to test lazy path
        assert state.experiment_api is not None
        state.experiment_api.close()
        state.experiment_api = None
        state.plans_dir = str(tmp_path / "plans")
        (tmp_path / "plans").mkdir()
        api = _get_experiment_api()
        try:
            assert api is not None
            assert (tmp_path / "plans" / "experiments.db").exists()
        finally:
            api.close()
            # Restore a clean state.experiment_api so the autouse teardown
            # has something to close.
            state.experiment_api = ExperimentAPI(tmp_path / "experiments.db")
