"""Tests for required_tools on PlanStep and validate_tool_policies."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swarm.errors import RegistryError
from swarm.mcp import state
from swarm.mcp.plan_tools import plan_execute_step, plan_validate_policies
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import validate_tool_policies
from swarm.registry.models import AgentDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plan(tmp_path: Path, plan_data: dict) -> Path:  # type: ignore[type-arg]
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


def _agent(name: str, tools: list[str]) -> AgentDefinition:
    return AgentDefinition(
        id=f"id-{name}",
        name=name,
        system_prompt="",
        tools=tuple(tools),
    )


# ---------------------------------------------------------------------------
# PlanStep.required_tools — model-level tests
# ---------------------------------------------------------------------------


class TestRequiredToolsField:
    def test_default_is_empty_tuple(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w")
        assert step.required_tools == ()

    def test_roundtrip_with_tools(self) -> None:
        step = PlanStep(
            id="s1",
            type="task",
            prompt="p",
            agent_type="w",
            required_tools=("Read", "Write", "Bash"),
        )
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.required_tools == ("Read", "Write", "Bash")

    def test_sparse_serialization_empty_omitted(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w")
        d = step.to_dict()
        assert "required_tools" not in d

    def test_sparse_serialization_nonempty_included(self) -> None:
        step = PlanStep(
            id="s1",
            type="task",
            prompt="p",
            agent_type="w",
            required_tools=("Grep",),
        )
        d = step.to_dict()
        assert d["required_tools"] == ["Grep"]

    def test_from_dict_backward_compat_missing_defaults_to_empty(self) -> None:
        old_dict = {
            "id": "legacy",
            "type": "task",
            "prompt": "do work",
            "agent_type": "worker",
        }
        step = PlanStep.from_dict(old_dict)
        assert step.required_tools == ()

    def test_from_dict_explicit_empty_list(self) -> None:
        d = {
            "id": "s1",
            "type": "task",
            "prompt": "p",
            "agent_type": "w",
            "required_tools": [],
        }
        step = PlanStep.from_dict(d)
        assert step.required_tools == ()

    def test_plan_roundtrip_preserves_required_tools(self) -> None:
        plan = Plan(
            version=1,
            goal="g",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="p",
                    agent_type="coder",
                    required_tools=("Read", "Write"),
                ),
            ],
        )
        restored = Plan.from_dict(plan.to_dict())
        assert restored.steps[0].required_tools == ("Read", "Write")


# ---------------------------------------------------------------------------
# validate_tool_policies
# ---------------------------------------------------------------------------


class TestValidateToolPolicies:
    def _make_plan(self, required_tools: tuple[str, ...]) -> Plan:
        return Plan(
            version=1,
            goal="g",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="p",
                    agent_type="coder",
                    required_tools=required_tools,
                )
            ],
        )

    def test_no_required_tools_returns_empty_warnings(self) -> None:
        mock_api = MagicMock()
        plan = self._make_plan(())
        warnings = validate_tool_policies(plan, mock_api)
        assert warnings == []
        mock_api.resolve_agent.assert_not_called()

    def test_agent_has_all_required_tools_no_warning(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read", "Write", "Bash"])
        plan = self._make_plan(("Read", "Write"))
        warnings = validate_tool_policies(plan, mock_api)
        assert warnings == []

    def test_agent_missing_one_tool_produces_warning(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read"])
        plan = self._make_plan(("Read", "Write"))
        warnings = validate_tool_policies(plan, mock_api)
        assert len(warnings) == 1
        assert "s1" in warnings[0]
        assert "coder" in warnings[0]
        assert "Write" in warnings[0]

    def test_agent_missing_multiple_tools_lists_all(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", [])
        # Agent has tools=() which means empty — should be skipped
        plan = self._make_plan(("Read", "Write"))
        warnings = validate_tool_policies(plan, mock_api)
        # Empty tools on agent → silently skip
        assert warnings == []

    def test_agent_not_found_skips_silently(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.side_effect = RegistryError("not found")
        plan = self._make_plan(("Read",))
        warnings = validate_tool_policies(plan, mock_api)
        assert warnings == []

    def test_agent_with_empty_tools_skips_silently(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", [])
        plan = self._make_plan(("Read",))
        warnings = validate_tool_policies(plan, mock_api)
        assert warnings == []

    def test_step_without_agent_type_skips(self) -> None:
        mock_api = MagicMock()
        plan = Plan(
            version=1,
            goal="g",
            steps=[
                PlanStep(
                    id="cp",
                    type="checkpoint",
                    prompt="p",
                    agent_type="",
                    required_tools=("Read",),
                )
            ],
        )
        warnings = validate_tool_policies(plan, mock_api)
        assert warnings == []
        mock_api.resolve_agent.assert_not_called()

    def test_multiple_steps_warns_for_each_mismatch(self) -> None:
        mock_api = MagicMock()

        def _side_effect(name: str) -> AgentDefinition:
            return _agent(name, ["Read"])

        mock_api.resolve_agent.side_effect = _side_effect

        plan = Plan(
            version=1,
            goal="g",
            steps=[
                PlanStep(
                    id="s1",
                    type="task",
                    prompt="p",
                    agent_type="coder",
                    required_tools=("Read", "Write"),
                ),
                PlanStep(
                    id="s2",
                    type="task",
                    prompt="p",
                    agent_type="reviewer",
                    required_tools=("Grep", "Read"),
                    depends_on=("s1",),
                ),
            ],
        )
        warnings = validate_tool_policies(plan, mock_api)
        assert len(warnings) == 2
        step_ids = {w.split("'")[1] for w in warnings}
        assert step_ids == {"s1", "s2"}

    def test_warning_message_format(self) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read"])
        plan = self._make_plan(("Read", "Write", "Bash"))
        warnings = validate_tool_policies(plan, mock_api)
        assert len(warnings) == 1
        # Missing tools listed in sorted order
        assert "['Bash', 'Write']" in warnings[0]


# ---------------------------------------------------------------------------
# plan_validate_policies MCP tool
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)
    state.registry_api = None


class TestPlanValidatePoliciesTool:
    def test_file_not_found_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_validate_policies(str(tmp_path / "missing.json")))
        assert "error" in result
        assert "Plan file not found" in result["error"]

    def test_no_registry_api_returns_empty_warnings(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "g",
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "p",
                    "agent_type": "coder",
                    "required_tools": ["Read"],
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        state.registry_api = None
        result = json.loads(plan_validate_policies(str(path)))
        assert result == {"warnings": []}

    def test_no_mismatches_returns_empty_warnings(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read", "Write"])
        state.registry_api = mock_api

        plan_data = {
            "version": 1,
            "goal": "g",
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "p",
                    "agent_type": "coder",
                    "required_tools": ["Read"],
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_validate_policies(str(path)))
        assert result["warnings"] == []

    def test_mismatch_returns_warnings(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read"])
        state.registry_api = mock_api

        plan_data = {
            "version": 1,
            "goal": "g",
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "p",
                    "agent_type": "coder",
                    "required_tools": ["Read", "Write"],
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_validate_policies(str(path)))
        assert len(result["warnings"]) == 1
        assert "s1" in result["warnings"][0]
        assert "Write" in result["warnings"][0]

    def test_plan_with_no_required_tools_returns_empty(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        state.registry_api = mock_api

        plan_data = {
            "version": 1,
            "goal": "g",
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "p",
                    "agent_type": "coder",
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_validate_policies(str(path)))
        assert result["warnings"] == []
        mock_api.resolve_agent.assert_not_called()


# ---------------------------------------------------------------------------
# plan_execute_step includes required_tools
# ---------------------------------------------------------------------------


class TestPlanExecuteStepRequiredTools:
    def setup_method(self) -> None:
        state.registry_api = None

    def test_required_tools_included_in_payload(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "g",
            "variables": {},
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "do work",
                    "agent_type": "coder",
                    "required_tools": ["Read", "Grep"],
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "s1"))
        assert result["required_tools"] == ["Read", "Grep"]

    def test_required_tools_empty_list_when_not_set(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "g",
            "variables": {},
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "do work",
                    "agent_type": "coder",
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "s1"))
        assert result["required_tools"] == []

    def test_required_tools_alongside_agent_tools(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = _agent("coder", ["Read", "Write", "Bash"])
        state.registry_api = mock_api

        plan_data = {
            "version": 1,
            "goal": "g",
            "variables": {},
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "do work",
                    "agent_type": "coder",
                    "required_tools": ["Read"],
                }
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "s1"))
        # tools = what agent has; required_tools = what step needs
        assert result["tools"] == ["Read", "Write", "Bash"]
        assert result["required_tools"] == ["Read"]
