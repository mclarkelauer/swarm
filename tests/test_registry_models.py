"""Tests for registry data models."""

from __future__ import annotations

from swarm.registry.models import AgentDefinition


def _make_agent(
    usage_count: int = 0,
    failure_count: int = 0,
) -> AgentDefinition:
    """Create a minimal AgentDefinition with the given counts."""
    return AgentDefinition(
        id="a1",
        name="test-agent",
        system_prompt="You are a test agent.",
        usage_count=usage_count,
        failure_count=failure_count,
    )


class TestSuccessRate:
    """Tests for AgentDefinition.success_rate property."""

    def test_success_rate_no_usage_returns_one(self) -> None:
        agent = _make_agent(usage_count=0, failure_count=0)
        assert agent.success_rate == 1.0

    def test_success_rate_no_failures(self) -> None:
        agent = _make_agent(usage_count=10, failure_count=0)
        assert agent.success_rate == 1.0

    def test_success_rate_some_failures(self) -> None:
        agent = _make_agent(usage_count=10, failure_count=3)
        assert agent.success_rate == 0.7

    def test_success_rate_all_failures(self) -> None:
        agent = _make_agent(usage_count=10, failure_count=10)
        assert agent.success_rate == 0.0

    def test_success_rate_in_to_dict(self) -> None:
        agent = _make_agent(usage_count=10, failure_count=3)
        d = agent.to_dict()
        assert "success_rate" in d
        assert d["success_rate"] == 0.7
