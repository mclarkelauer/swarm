"""Tests for agent_metrics table in swarm.registry.api."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.registry.api import RegistryAPI


@pytest.fixture()
def api(tmp_path: Path) -> RegistryAPI:
    return RegistryAPI(tmp_path / "registry.db")


class TestRecordMetric:
    def test_record_metric_creates_entry(self, api: RegistryAPI) -> None:
        result = api.record_metric("code-reviewer", success=True, duration_seconds=12.5)
        assert result["agent_name"] == "code-reviewer"
        assert result["total_runs"] == 1
        assert result["total_successes"] == 1
        assert result["total_failures"] == 0
        assert result["avg_duration_seconds"] == 12.5

    def test_record_metric_accumulates(self, api: RegistryAPI) -> None:
        api.record_metric("code-reviewer", success=True, duration_seconds=10.0, tokens_used=100, cost_usd=0.01)
        api.record_metric("code-reviewer", success=True, duration_seconds=20.0, tokens_used=200, cost_usd=0.02)
        result = api.record_metric("code-reviewer", success=True, duration_seconds=30.0, tokens_used=300, cost_usd=0.03)

        assert result["total_runs"] == 3
        assert result["total_successes"] == 3
        assert result["total_failures"] == 0
        assert result["total_tokens"] == 600
        assert result["total_cost_usd"] == pytest.approx(0.06)

    def test_record_metric_failure(self, api: RegistryAPI) -> None:
        api.record_metric("buggy-agent", success=True)
        result = api.record_metric("buggy-agent", success=False)

        assert result["total_runs"] == 2
        assert result["total_successes"] == 1
        assert result["total_failures"] == 1


class TestGetMetrics:
    def test_get_metrics_nonexistent(self, api: RegistryAPI) -> None:
        assert api.get_metrics("no-such-agent") is None

    def test_get_metrics_success_rate(self, api: RegistryAPI) -> None:
        api.record_metric("mixed-agent", success=True)
        api.record_metric("mixed-agent", success=True)
        api.record_metric("mixed-agent", success=False)
        api.record_metric("mixed-agent", success=False)

        result = api.get_metrics("mixed-agent")
        assert result is not None
        assert result["success_rate"] == pytest.approx(0.5)


class TestListMetrics:
    def test_list_metrics_ordered_by_runs(self, api: RegistryAPI) -> None:
        api.record_metric("less-used", success=True)
        api.record_metric("most-used", success=True)
        api.record_metric("most-used", success=True)
        api.record_metric("most-used", success=True)
        api.record_metric("mid-used", success=True)
        api.record_metric("mid-used", success=True)

        results = api.list_metrics()
        assert len(results) == 3
        assert results[0]["agent_name"] == "most-used"
        assert results[0]["total_runs"] == 3
        assert results[1]["agent_name"] == "mid-used"
        assert results[1]["total_runs"] == 2
        assert results[2]["agent_name"] == "less-used"
        assert results[2]["total_runs"] == 1

    def test_list_metrics_empty(self, api: RegistryAPI) -> None:
        assert api.list_metrics() == []
