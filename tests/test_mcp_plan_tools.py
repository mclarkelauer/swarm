"""Tests for swarm.mcp.plan_tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.plan_tools import (
    plan_create,
    plan_get_ready_steps,
    plan_get_step,
    plan_list,
    plan_load,
    plan_validate,
)


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
