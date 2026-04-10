"""Tests for MCP registry metrics tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.registry_tools import registry_get_metrics, registry_record_metric
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")


class TestRegistryRecordMetric:
    def test_registry_record_metric_tool(self) -> None:
        result = json.loads(registry_record_metric("test-agent", success="true", duration_seconds="5.0", tokens_used="150", cost_usd="0.02"))
        assert result["agent_name"] == "test-agent"
        assert result["total_runs"] == 1
        assert result["total_successes"] == 1
        assert result["total_tokens"] == 150
        assert result["total_cost_usd"] == pytest.approx(0.02)


class TestRegistryGetMetrics:
    def test_registry_get_metrics_tool(self) -> None:
        assert state.registry_api is not None
        state.registry_api.record_metric("my-agent", success=True, tokens_used=100)
        result = json.loads(registry_get_metrics("my-agent"))
        assert result["agent_name"] == "my-agent"
        assert result["total_runs"] == 1

    def test_registry_get_metrics_all_tool(self) -> None:
        assert state.registry_api is not None
        state.registry_api.record_metric("agent-a", success=True)
        state.registry_api.record_metric("agent-b", success=True)
        result = json.loads(registry_get_metrics(""))
        assert isinstance(result, list)
        assert len(result) == 2

    def test_registry_get_metrics_not_found(self) -> None:
        result = json.loads(registry_get_metrics("nonexistent"))
        assert "error" in result
