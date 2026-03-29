"""Tests for swarm.forge.prompts: FORGE_SYSTEM_PROMPT, build_forge_prompt."""

from __future__ import annotations

from swarm.forge.prompts import FORGE_SYSTEM_PROMPT, build_forge_prompt
from swarm.registry.models import AgentDefinition


class TestForgeSystemPrompt:
    def test_contains_instructions(self) -> None:
        assert "Agent Forge" in FORGE_SYSTEM_PROMPT
        assert "JSON" in FORGE_SYSTEM_PROMPT

    def test_mentions_required_fields(self) -> None:
        assert "name" in FORGE_SYSTEM_PROMPT
        assert "system_prompt" in FORGE_SYSTEM_PROMPT
        assert "tools" in FORGE_SYSTEM_PROMPT
        assert "permissions" in FORGE_SYSTEM_PROMPT


class TestBuildForgePrompt:
    def test_includes_task(self) -> None:
        result = build_forge_prompt("write tests", [])
        assert "write tests" in result

    def test_includes_existing_agents(self) -> None:
        agents = [
            AgentDefinition(
                id="1", name="researcher", system_prompt="You research topics.",
                tools=(), permissions=(), source="forge",
            ),
        ]
        result = build_forge_prompt("do research", agents)
        assert "researcher" in result
        assert "You research topics." in result

    def test_empty_agents_list(self) -> None:
        result = build_forge_prompt("task", [])
        assert "Existing agents" not in result

    def test_suggests_reuse(self) -> None:
        # The prompt should encourage starting from an existing base agent
        # rather than building from scratch, regardless of phrasing.
        result = build_forge_prompt("task", [])
        assert (
            "reusing" in result.lower()
            or "cloning" in result.lower()
            or "base agent" in result.lower()
            or "closest" in result.lower()
        )
