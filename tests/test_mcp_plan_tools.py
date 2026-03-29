"""Tests for swarm.mcp.plan_tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swarm.errors import RegistryError
from swarm.mcp import state
from swarm.mcp.plan_tools import (
    _safe_interpolate,
    plan_create,
    plan_execute_step,
    plan_get_ready_steps,
    plan_get_step,
    plan_list,
    plan_load,
    plan_validate,
)
from swarm.registry.models import AgentDefinition


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)


def _basic_steps_json() -> str:
    return json.dumps([
        {"id": "s1", "type": "task", "prompt": "do stuff", "agent_type": "worker"},
        {"id": "s2", "type": "task", "prompt": "next", "agent_type": "worker", "depends_on": ["s1"]},
    ])


class TestPlanCreate:
    def test_creates_and_saves(self, tmp_path: Path) -> None:
        result = json.loads(plan_create("test goal", _basic_steps_json()))
        assert result["errors"] == []
        assert result["version"] == 1
        assert Path(result["path"]).exists()

    def test_returns_errors_for_invalid(self) -> None:
        result = json.loads(plan_create("", "[]"))
        assert len(result["errors"]) > 0
        assert result["path"] is None

    def test_auto_increments_version(self, tmp_path: Path) -> None:
        plan_create("goal 1", _basic_steps_json())
        result = json.loads(plan_create("goal 2", _basic_steps_json()))
        assert result["version"] == 2

    def test_custom_plans_dir(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom_plans"
        custom.mkdir()
        result = json.loads(plan_create("goal", _basic_steps_json(), plans_dir=str(custom)))
        assert str(custom) in result["path"]

    def test_with_variables(self) -> None:
        variables = json.dumps({"topic": "testing"})
        result = json.loads(plan_create("research {topic}", _basic_steps_json(), variables))
        assert result["errors"] == []

    def test_cycle_detection(self) -> None:
        steps = json.dumps([
            {"id": "a", "type": "task", "prompt": "p", "agent_type": "w", "depends_on": ["b"]},
            {"id": "b", "type": "task", "prompt": "p", "agent_type": "w", "depends_on": ["a"]},
        ])
        result = json.loads(plan_create("goal", steps))
        assert len(result["errors"]) > 0


class TestPlanValidate:
    def test_valid_plan(self) -> None:
        plan_data = {
            "version": 1, "goal": "g",
            "steps": [{"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"}],
        }
        result = json.loads(plan_validate(json.dumps(plan_data)))
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_plan(self) -> None:
        plan_data = {"version": 1, "goal": "", "steps": []}
        result = json.loads(plan_validate(json.dumps(plan_data)))
        assert result["valid"] is False


class TestPlanLoad:
    def test_loads_saved_plan(self, tmp_path: Path) -> None:
        create_result = json.loads(plan_create("my goal", _basic_steps_json()))
        loaded = json.loads(plan_load(create_result["path"]))
        assert loaded["goal"] == "my goal"
        assert len(loaded["steps"]) == 2


class TestPlanList:
    def test_empty(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = json.loads(plan_list(str(empty_dir)))
        assert result == []

    def test_lists_versions(self, tmp_path: Path) -> None:
        plan_create("goal 1", _basic_steps_json())
        plan_create("goal 2", _basic_steps_json())
        result = json.loads(plan_list())
        assert len(result) == 2
        assert result[0]["version"] == 1
        assert result[1]["version"] == 2


class TestPlanGetReadySteps:
    def test_initial_ready(self) -> None:
        plan_data = {
            "version": 1, "goal": "g",
            "steps": [
                {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "s2", "type": "task", "prompt": "p", "agent_type": "w", "depends_on": ["s1"]},
            ],
        }
        result = json.loads(plan_get_ready_steps(json.dumps(plan_data)))
        assert len(result) == 1
        assert result[0]["id"] == "s1"

    def test_after_completion(self) -> None:
        plan_data = {
            "version": 1, "goal": "g",
            "steps": [
                {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "s2", "type": "task", "prompt": "p", "agent_type": "w", "depends_on": ["s1"]},
            ],
        }
        result = json.loads(plan_get_ready_steps(json.dumps(plan_data), '["s1"]'))
        assert len(result) == 1
        assert result[0]["id"] == "s2"


class TestPlanGetReadyStepsWithArtifactsDir:
    def test_plan_get_ready_steps_with_artifacts_dir(self, tmp_path: Path) -> None:
        # Create the required input file
        (tmp_path / "prereq.md").write_text("prereq content", encoding="utf-8")

        plan_data = {
            "version": 1,
            "goal": "test artifacts",
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "prompt": "needs prereq",
                    "agent_type": "worker",
                    "required_inputs": ["prereq.md"],
                },
                {
                    "id": "s2",
                    "type": "task",
                    "prompt": "needs missing file",
                    "agent_type": "worker",
                    "required_inputs": ["missing.md"],
                },
            ],
        }

        result = json.loads(
            plan_get_ready_steps(
                json.dumps(plan_data),
                "[]",
                artifacts_dir=str(tmp_path),
            )
        )

        ready_ids = {s["id"] for s in result}
        # s1's input exists → ready; s2's input missing → not ready
        assert "s1" in ready_ids
        assert "s2" not in ready_ids


class TestPlanGetStep:
    def test_finds_step(self) -> None:
        plan_data = {
            "version": 1, "goal": "g",
            "steps": [{"id": "s1", "type": "task", "prompt": "do it", "agent_type": "w"}],
        }
        result = json.loads(plan_get_step(json.dumps(plan_data), "s1"))
        assert result["id"] == "s1"
        assert result["prompt"] == "do it"

    def test_not_found(self) -> None:
        plan_data = {"version": 1, "goal": "g", "steps": []}
        result = json.loads(plan_get_step(json.dumps(plan_data), "missing"))
        assert "error" in result


# ---------------------------------------------------------------------------
# _safe_interpolate unit tests
# ---------------------------------------------------------------------------

class TestSafeInterpolate:
    def test_replaces_known_key(self) -> None:
        assert _safe_interpolate("Hello {name}!", {"name": "world"}) == "Hello world!"

    def test_leaves_unknown_key_intact(self) -> None:
        assert _safe_interpolate("Hello {unknown}!", {}) == "Hello {unknown}!"

    def test_partial_replacement(self) -> None:
        result = _safe_interpolate("{a} and {b}", {"a": "alpha"})
        assert result == "alpha and {b}"

    def test_empty_template(self) -> None:
        assert _safe_interpolate("", {"key": "val"}) == ""

    def test_empty_variables(self) -> None:
        assert _safe_interpolate("no vars here", {}) == "no vars here"

    def test_multiple_occurrences(self) -> None:
        result = _safe_interpolate("{x} {x} {x}", {"x": "go"})
        assert result == "go go go"


# ---------------------------------------------------------------------------
# plan_execute_step tool tests
# ---------------------------------------------------------------------------

def _write_plan(tmp_path: Path, plan_data: dict) -> Path:  # type: ignore[type-arg]
    """Write a plan dict to a JSON file and return the path."""
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


def _basic_plan_data() -> dict:  # type: ignore[type-arg]
    return {
        "version": 1,
        "goal": "test goal",
        "variables": {"env": "production"},
        "steps": [
            {
                "id": "review",
                "type": "task",
                "prompt": "Review code for {env}",
                "agent_type": "code-reviewer",
                "output_artifact": "review.md",
            },
            {
                "id": "deploy",
                "type": "task",
                "prompt": "Deploy to {env} using {strategy}",
                "agent_type": "deployer",
                "spawn_mode": "background",
            },
        ],
    }


class TestPlanExecuteStep:
    def setup_method(self) -> None:
        # Reset registry_api to None before each test
        state.registry_api = None

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = json.loads(plan_execute_step(str(tmp_path / "missing.json"), "review"))
        assert "error" in result
        assert "Plan file not found" in result["error"]

    def test_step_not_found(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "nonexistent"))
        assert "error" in result
        assert "nonexistent" in result["error"]
        assert "not found in plan" in result["error"]

    def test_invalid_variables_json(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review", "{not valid json"))
        assert "error" in result
        assert "Invalid variables_json" in result["error"]

    def test_prompt_interpolation_with_plan_variables(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review"))
        assert result["prompt"] == "Review code for production"

    def test_caller_variables_override_plan_variables(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review", json.dumps({"env": "staging"})))
        assert result["prompt"] == "Review code for staging"

    def test_unknown_placeholder_left_intact(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "deploy"))
        # {strategy} is not in variables — must remain as-is
        assert "{strategy}" in result["prompt"]
        assert "production" in result["prompt"]

    def test_step_fields_in_payload(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review"))
        assert result["agent_type"] == "code-reviewer"
        assert result["spawn_mode"] == "foreground"
        assert result["output_artifact"] == "review.md"

    def test_no_registry_api_returns_null_description_and_tools(self, tmp_path: Path) -> None:
        state.registry_api = None
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review"))
        assert result["description"] is None
        assert result["tools"] is None

    def test_registry_api_found_enriches_payload(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.return_value = AgentDefinition(
            id="abc",
            name="code-reviewer",
            system_prompt="You review code.",
            tools=("Read", "Grep"),
            description="Reviews Python code for security vulnerabilities",
        )
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review"))

        assert result["description"] == "Reviews Python code for security vulnerabilities"
        assert result["tools"] == ["Read", "Grep"]
        mock_api.resolve_agent.assert_called_once_with("code-reviewer")

    def test_registry_api_not_found_returns_null(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.side_effect = RegistryError("Agent not found")
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "review"))

        assert result["description"] is None
        assert result["tools"] is None
        # Core fields should still be present
        assert result["agent_type"] == "code-reviewer"
        assert result["prompt"] == "Review code for production"

    def test_empty_agent_type_skips_registry_lookup(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        state.registry_api = mock_api

        plan_data = {
            "version": 1,
            "goal": "g",
            "variables": {},
            "steps": [{"id": "chk", "type": "checkpoint", "prompt": "Pause here"}],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "chk"))

        mock_api.resolve_agent.assert_not_called()
        assert result["agent_type"] == ""
        assert result["description"] is None
        assert result["tools"] is None

    def test_background_spawn_mode_preserved(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_execute_step(str(path), "deploy"))
        assert result["spawn_mode"] == "background"

    def test_variables_json_supplies_missing_placeholder(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(
            plan_execute_step(str(path), "deploy", json.dumps({"strategy": "blue-green"}))
        )
        assert "blue-green" in result["prompt"]
        assert "{strategy}" not in result["prompt"]
