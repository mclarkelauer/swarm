"""Tests for swarm.experiments.api: ExperimentAPI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.experiments.api import ExperimentAPI


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[ExperimentAPI]:
    api = ExperimentAPI(tmp_path / "experiments.db")
    try:
        yield api
    finally:
        api.close()


class TestCreateExperiment:
    def test_create_returns_experiment_dict(self, api: ExperimentAPI) -> None:
        result = api.create("test-exp", "agent-v1", "agent-v2")
        assert result["name"] == "test-exp"
        assert result["agent_a"] == "agent-v1"
        assert result["agent_b"] == "agent-v2"
        assert result["traffic_pct"] == 50.0
        assert result["status"] == "active"

    def test_create_with_custom_traffic(self, api: ExperimentAPI) -> None:
        result = api.create("exp", "a1", "a2", traffic_pct=20.0)
        assert result["traffic_pct"] == 20.0

    def test_create_duplicate_name_raises(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        with pytest.raises(Exception):  # noqa: B017
            api.create("exp", "a3", "a4")


class TestResolveVariant:
    def test_resolve_returns_agent_and_label(self, api: ExperimentAPI) -> None:
        api.create("exp", "agent-a", "agent-b", traffic_pct=50.0)
        agent, variant = api.resolve_variant("exp")
        assert agent in ("agent-a", "agent-b")
        assert variant in ("A", "B")

    def test_resolve_100pct_always_b(self, api: ExperimentAPI) -> None:
        api.create("exp", "agent-a", "agent-b", traffic_pct=100.0)
        for _ in range(20):
            agent, variant = api.resolve_variant("exp")
            assert agent == "agent-b"
            assert variant == "B"

    def test_resolve_0pct_always_a(self, api: ExperimentAPI) -> None:
        api.create("exp", "agent-a", "agent-b", traffic_pct=0.0)
        for _ in range(20):
            agent, variant = api.resolve_variant("exp")
            assert agent == "agent-a"
            assert variant == "A"

    def test_resolve_not_found_raises(self, api: ExperimentAPI) -> None:
        with pytest.raises(ValueError, match="not found"):
            api.resolve_variant("nonexistent")

    def test_resolve_ended_experiment_raises(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        api.end_experiment("exp")
        with pytest.raises(ValueError, match="ended"):
            api.resolve_variant("exp")


class TestRecordResult:
    def test_record_result_stores_entry(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        result = api.record_result("exp", "A", success=True, duration_secs=5.0)
        assert result["variant"] == "A"
        assert result["success"] is True

    def test_record_result_not_found_raises(self, api: ExperimentAPI) -> None:
        with pytest.raises(ValueError, match="not found"):
            api.record_result("nonexistent", "A")


class TestGetResults:
    def test_get_results_aggregates(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        api.record_result("exp", "A", success=True, tokens_used=100)
        api.record_result("exp", "A", success=True, tokens_used=200)
        api.record_result("exp", "A", success=False, tokens_used=50)
        api.record_result("exp", "B", success=True, tokens_used=150)
        api.record_result("exp", "B", success=True, tokens_used=100)

        results = api.get_results("exp")
        assert results["name"] == "exp"
        va = results["variants"]["A"]
        assert va["total_runs"] == 3
        assert va["successes"] == 2
        assert va["failures"] == 1
        assert va["total_tokens"] == 350

        vb = results["variants"]["B"]
        assert vb["total_runs"] == 2
        assert vb["successes"] == 2
        assert vb["success_rate"] == 1.0

    def test_get_results_determines_winner(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        api.record_result("exp", "A", success=True)
        api.record_result("exp", "A", success=False)
        api.record_result("exp", "B", success=True)
        api.record_result("exp", "B", success=True)

        results = api.get_results("exp")
        assert results["winner"] == "B"

    def test_get_results_no_data(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        results = api.get_results("exp")
        assert results["winner"] is None
        assert results["variants"]["A"]["total_runs"] == 0

    def test_get_results_not_found_raises(self, api: ExperimentAPI) -> None:
        with pytest.raises(ValueError, match="not found"):
            api.get_results("nonexistent")


class TestEndExperiment:
    def test_end_marks_as_ended(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        assert api.end_experiment("exp") is True
        exps = api.list_experiments(status="ended")
        assert len(exps) == 1

    def test_end_nonexistent_returns_false(self, api: ExperimentAPI) -> None:
        assert api.end_experiment("nonexistent") is False

    def test_end_already_ended_returns_false(self, api: ExperimentAPI) -> None:
        api.create("exp", "a1", "a2")
        api.end_experiment("exp")
        assert api.end_experiment("exp") is False


class TestListExperiments:
    def test_list_all(self, api: ExperimentAPI) -> None:
        api.create("exp1", "a1", "a2")
        api.create("exp2", "b1", "b2")
        exps = api.list_experiments()
        assert len(exps) == 2

    def test_list_filtered_by_status(self, api: ExperimentAPI) -> None:
        api.create("exp1", "a1", "a2")
        api.create("exp2", "b1", "b2")
        api.end_experiment("exp1")
        active = api.list_experiments(status="active")
        assert len(active) == 1
        assert active[0]["name"] == "exp2"

    def test_list_empty(self, api: ExperimentAPI) -> None:
        assert api.list_experiments() == []
