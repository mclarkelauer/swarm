"""Tests for fan-out/fan-in step types: models, parser, and plan_execute_step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.plan_tools import plan_execute_step
from swarm.plan.models import FanOutBranch, FanOutConfig, Plan, PlanStep
from swarm.plan.parser import validate_plan


# ---------------------------------------------------------------------------
# FanOutBranch tests
# ---------------------------------------------------------------------------


class TestFanOutBranch:
    def test_basic_construction(self) -> None:
        b = FanOutBranch(agent_type="worker", prompt="do work")
        assert b.agent_type == "worker"
        assert b.prompt == "do work"
        assert b.output_artifact == ""

    def test_with_output_artifact(self) -> None:
        b = FanOutBranch(agent_type="writer", prompt="write docs", output_artifact="docs.md")
        assert b.output_artifact == "docs.md"

    def test_to_dict_excludes_empty_output_artifact(self) -> None:
        b = FanOutBranch(agent_type="worker", prompt="do it")
        d = b.to_dict()
        assert d == {"agent_type": "worker", "prompt": "do it"}
        assert "output_artifact" not in d

    def test_to_dict_includes_output_artifact_when_set(self) -> None:
        b = FanOutBranch(agent_type="writer", prompt="write", output_artifact="out.md")
        d = b.to_dict()
        assert d["output_artifact"] == "out.md"

    def test_from_dict_roundtrip_without_artifact(self) -> None:
        b = FanOutBranch(agent_type="worker", prompt="do work")
        restored = FanOutBranch.from_dict(b.to_dict())
        assert restored == b

    def test_from_dict_roundtrip_with_artifact(self) -> None:
        b = FanOutBranch(agent_type="writer", prompt="write docs", output_artifact="report.md")
        restored = FanOutBranch.from_dict(b.to_dict())
        assert restored == b

    def test_from_dict_defaults_missing_output_artifact(self) -> None:
        d = {"agent_type": "worker", "prompt": "do work"}
        b = FanOutBranch.from_dict(d)
        assert b.output_artifact == ""

    def test_from_dict_defaults_missing_prompt(self) -> None:
        d = {"agent_type": "worker"}
        b = FanOutBranch.from_dict(d)
        assert b.prompt == ""

    def test_is_frozen(self) -> None:
        b = FanOutBranch(agent_type="worker", prompt="do it")
        with pytest.raises((AttributeError, TypeError)):
            b.agent_type = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FanOutConfig tests
# ---------------------------------------------------------------------------


class TestFanOutConfig:
    def test_empty_config(self) -> None:
        cfg = FanOutConfig()
        assert cfg.branches == ()

    def test_with_branches(self) -> None:
        b1 = FanOutBranch(agent_type="a1", prompt="p1")
        b2 = FanOutBranch(agent_type="a2", prompt="p2")
        cfg = FanOutConfig(branches=(b1, b2))
        assert len(cfg.branches) == 2

    def test_to_dict(self) -> None:
        b1 = FanOutBranch(agent_type="a1", prompt="p1")
        b2 = FanOutBranch(agent_type="a2", prompt="p2", output_artifact="out.md")
        cfg = FanOutConfig(branches=(b1, b2))
        d = cfg.to_dict()
        assert "branches" in d
        assert len(d["branches"]) == 2
        assert d["branches"][0] == {"agent_type": "a1", "prompt": "p1"}
        assert d["branches"][1]["output_artifact"] == "out.md"

    def test_from_dict_roundtrip(self) -> None:
        b1 = FanOutBranch(agent_type="a1", prompt="p1")
        b2 = FanOutBranch(agent_type="a2", prompt="p2", output_artifact="out.md")
        cfg = FanOutConfig(branches=(b1, b2))
        restored = FanOutConfig.from_dict(cfg.to_dict())
        assert restored == cfg

    def test_from_dict_missing_branches_defaults_empty(self) -> None:
        cfg = FanOutConfig.from_dict({})
        assert cfg.branches == ()

    def test_is_frozen(self) -> None:
        cfg = FanOutConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.branches = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlanStep fan_out_config field
# ---------------------------------------------------------------------------


class TestPlanStepFanOutConfig:
    def test_default_is_none(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w")
        assert step.fan_out_config is None

    def test_sparse_serialization_omits_none(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p", agent_type="w")
        d = step.to_dict()
        assert "fan_out_config" not in d

    def test_sparse_serialization_includes_when_set(self) -> None:
        cfg = FanOutConfig(branches=(
            FanOutBranch(agent_type="a", prompt="p1"),
            FanOutBranch(agent_type="b", prompt="p2"),
        ))
        step = PlanStep(id="fo", type="fan_out", prompt="", fan_out_config=cfg)
        d = step.to_dict()
        assert "fan_out_config" in d
        assert len(d["fan_out_config"]["branches"]) == 2

    def test_roundtrip_with_fan_out_config(self) -> None:
        cfg = FanOutConfig(branches=(
            FanOutBranch(agent_type="alpha", prompt="do alpha", output_artifact="alpha.md"),
            FanOutBranch(agent_type="beta", prompt="do beta"),
        ))
        step = PlanStep(id="fo", type="fan_out", prompt="", fan_out_config=cfg)
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.fan_out_config is not None
        assert len(restored.fan_out_config.branches) == 2
        assert restored.fan_out_config.branches[0].agent_type == "alpha"
        assert restored.fan_out_config.branches[0].output_artifact == "alpha.md"
        assert restored.fan_out_config.branches[1].agent_type == "beta"

    def test_backward_compat_missing_fan_out_config(self) -> None:
        d = {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"}
        step = PlanStep.from_dict(d)
        assert step.fan_out_config is None


# ---------------------------------------------------------------------------
# Parser validation — fan_out
# ---------------------------------------------------------------------------


def _fan_out_plan(branches: list[dict]) -> Plan:  # type: ignore[type-arg]
    step_data: dict = {  # type: ignore[type-arg]
        "id": "fo",
        "type": "fan_out",
        "prompt": "",
        "fan_out_config": {"branches": branches},
    }
    return Plan.from_dict({
        "version": 1,
        "goal": "spread work",
        "steps": [step_data],
    })


class TestValidateFanOut:
    def test_valid_fan_out_two_branches(self) -> None:
        plan = _fan_out_plan([
            {"agent_type": "a1", "prompt": "do p1"},
            {"agent_type": "a2", "prompt": "do p2"},
        ])
        errors = validate_plan(plan)
        assert errors == []

    def test_valid_fan_out_three_branches(self) -> None:
        plan = _fan_out_plan([
            {"agent_type": "a1", "prompt": "p1"},
            {"agent_type": "a2", "prompt": "p2"},
            {"agent_type": "a3", "prompt": "p3"},
        ])
        errors = validate_plan(plan)
        assert errors == []

    def test_fan_out_missing_config(self) -> None:
        plan = Plan.from_dict({
            "version": 1,
            "goal": "g",
            "steps": [{"id": "fo", "type": "fan_out", "prompt": ""}],
        })
        errors = validate_plan(plan)
        assert any("fan_out_config" in e for e in errors)

    def test_fan_out_only_one_branch(self) -> None:
        plan = _fan_out_plan([{"agent_type": "a1", "prompt": "p1"}])
        errors = validate_plan(plan)
        assert any("at least 2 branches" in e for e in errors)

    def test_fan_out_zero_branches(self) -> None:
        plan = _fan_out_plan([])
        errors = validate_plan(plan)
        assert any("at least 2 branches" in e for e in errors)

    def test_fan_out_branch_missing_agent_type(self) -> None:
        plan = _fan_out_plan([
            {"agent_type": "", "prompt": "p1"},
            {"agent_type": "a2", "prompt": "p2"},
        ])
        errors = validate_plan(plan)
        assert any("agent_type" in e for e in errors)

    def test_fan_out_branch_missing_prompt(self) -> None:
        plan = _fan_out_plan([
            {"agent_type": "a1", "prompt": ""},
            {"agent_type": "a2", "prompt": "p2"},
        ])
        errors = validate_plan(plan)
        assert any("prompt" in e for e in errors)

    def test_fan_out_branch_both_missing(self) -> None:
        plan = _fan_out_plan([
            {"agent_type": "", "prompt": ""},
            {"agent_type": "a2", "prompt": "p2"},
        ])
        errors = validate_plan(plan)
        assert any("agent_type" in e for e in errors)
        assert any("prompt" in e for e in errors)


# ---------------------------------------------------------------------------
# Parser validation — join
# ---------------------------------------------------------------------------


class TestValidateJoin:
    def test_valid_join_with_depends_on(self) -> None:
        plan = Plan.from_dict({
            "version": 1,
            "goal": "gather",
            "steps": [
                {"id": "fo", "type": "fan_out", "prompt": "", "fan_out_config": {"branches": [
                    {"agent_type": "a1", "prompt": "p1"},
                    {"agent_type": "a2", "prompt": "p2"},
                ]}},
                {"id": "join1", "type": "join", "prompt": "merge results", "depends_on": ["fo"]},
            ],
        })
        errors = validate_plan(plan)
        assert errors == []

    def test_join_without_depends_on_errors(self) -> None:
        plan = Plan.from_dict({
            "version": 1,
            "goal": "gather",
            "steps": [
                {"id": "join1", "type": "join", "prompt": "merge"},
            ],
        })
        errors = validate_plan(plan)
        assert any("depends_on" in e for e in errors)

    def test_join_with_multiple_depends_on(self) -> None:
        plan = Plan.from_dict({
            "version": 1,
            "goal": "gather",
            "steps": [
                {"id": "a", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "b", "type": "task", "prompt": "p", "agent_type": "w"},
                {"id": "join1", "type": "join", "prompt": "merge", "depends_on": ["a", "b"]},
            ],
        })
        errors = validate_plan(plan)
        assert errors == []


# ---------------------------------------------------------------------------
# plan_execute_step — fan_out and join
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)
    state.registry_api = None


def _write_plan(tmp_path: Path, plan_data: dict) -> Path:  # type: ignore[type-arg]
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


class TestPlanExecuteStepFanOut:
    def test_returns_branches_array(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "spread work",
            "variables": {},
            "steps": [
                {
                    "id": "fo",
                    "type": "fan_out",
                    "prompt": "",
                    "fan_out_config": {
                        "branches": [
                            {"agent_type": "researcher", "prompt": "Research topic A", "output_artifact": "a.md"},
                            {"agent_type": "writer", "prompt": "Write section B", "output_artifact": "b.md"},
                        ],
                    },
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "fo"))

        assert result["step_type"] == "fan_out"
        assert "branches" in result
        assert len(result["branches"]) == 2

        assert result["branches"][0]["agent_type"] == "researcher"
        assert result["branches"][0]["prompt"] == "Research topic A"
        assert result["branches"][0]["output_artifact"] == "a.md"

        assert result["branches"][1]["agent_type"] == "writer"
        assert result["branches"][1]["prompt"] == "Write section B"
        assert result["branches"][1]["output_artifact"] == "b.md"

    def test_branches_without_output_artifact(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "spread work",
            "variables": {},
            "steps": [
                {
                    "id": "fo",
                    "type": "fan_out",
                    "prompt": "",
                    "fan_out_config": {
                        "branches": [
                            {"agent_type": "a1", "prompt": "p1"},
                            {"agent_type": "a2", "prompt": "p2"},
                        ],
                    },
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "fo"))

        assert result["step_type"] == "fan_out"
        assert len(result["branches"]) == 2
        # output_artifact absent when empty (sparse)
        assert "output_artifact" not in result["branches"][0]

    def test_three_branches(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "spread work",
            "variables": {},
            "steps": [
                {
                    "id": "fo",
                    "type": "fan_out",
                    "prompt": "",
                    "fan_out_config": {
                        "branches": [
                            {"agent_type": "a1", "prompt": "p1"},
                            {"agent_type": "a2", "prompt": "p2"},
                            {"agent_type": "a3", "prompt": "p3"},
                        ],
                    },
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "fo"))
        assert len(result["branches"]) == 3


class TestPlanExecuteStepJoin:
    def test_returns_join_inputs_with_dep_ids(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "gather",
            "variables": {},
            "steps": [
                {
                    "id": "fo",
                    "type": "fan_out",
                    "prompt": "",
                    "fan_out_config": {
                        "branches": [
                            {"agent_type": "a1", "prompt": "p1", "output_artifact": "a1.md"},
                            {"agent_type": "a2", "prompt": "p2", "output_artifact": "a2.md"},
                        ],
                    },
                },
                {
                    "id": "join1",
                    "type": "join",
                    "prompt": "merge results",
                    "depends_on": ["fo"],
                    "output_artifact": "merged.md",
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "join1"))

        assert result["step_type"] == "join"
        assert "join_inputs" in result
        assert len(result["join_inputs"]) == 1
        assert result["join_inputs"][0]["step_id"] == "fo"

    def test_join_includes_output_artifact_from_dep(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "gather",
            "variables": {},
            "steps": [
                {
                    "id": "branch_a",
                    "type": "task",
                    "prompt": "do a",
                    "agent_type": "worker",
                    "output_artifact": "result_a.md",
                },
                {
                    "id": "branch_b",
                    "type": "task",
                    "prompt": "do b",
                    "agent_type": "worker",
                    "output_artifact": "result_b.md",
                },
                {
                    "id": "join1",
                    "type": "join",
                    "prompt": "merge",
                    "depends_on": ["branch_a", "branch_b"],
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "join1"))

        assert result["step_type"] == "join"
        join_inputs = result["join_inputs"]
        assert len(join_inputs) == 2

        by_id = {ji["step_id"]: ji for ji in join_inputs}
        assert by_id["branch_a"]["output_artifact"] == "result_a.md"
        assert by_id["branch_b"]["output_artifact"] == "result_b.md"

    def test_join_dep_with_no_output_artifact(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "gather",
            "variables": {},
            "steps": [
                {
                    "id": "prior",
                    "type": "task",
                    "prompt": "do it",
                    "agent_type": "worker",
                    # no output_artifact
                },
                {
                    "id": "join1",
                    "type": "join",
                    "prompt": "merge",
                    "depends_on": ["prior"],
                },
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "join1"))

        assert result["step_type"] == "join"
        assert result["join_inputs"][0]["step_id"] == "prior"
        assert result["join_inputs"][0]["output_artifact"] == ""
