"""Tests for the critic loop pattern on PlanStep.

Covers:
- models.py: critic_agent / max_critic_iterations fields, roundtrip, sparse
  serialization, and backward-compat defaults.
- parser.py: validation rules (non-task step error, min-iterations error,
  orphaned-max-iterations warning).
- plan_tools.py: plan_execute_step returns a "critic" key when critic_agent is
  set, omits it when empty, and resolves the critic agent from the registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swarm.errors import RegistryError
from swarm.mcp import state
from swarm.mcp.plan_tools import plan_execute_step
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import validate_plan
from swarm.registry.models import AgentDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_step(**kwargs: object) -> PlanStep:
    """Return a minimal valid task PlanStep, overriding fields via kwargs."""
    base: dict[str, object] = {
        "id": "s1",
        "type": "task",
        "prompt": "do work",
        "agent_type": "worker",
    }
    base.update(kwargs)
    return PlanStep.from_dict(base)


def _single_step_plan(step: PlanStep) -> Plan:
    return Plan(version=1, goal="test goal", steps=[step])


def _write_plan(tmp_path: Path, plan_data: dict) -> Path:  # type: ignore[type-arg]
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# models.py — field defaults
# ---------------------------------------------------------------------------


class TestPlanStepCriticDefaults:
    def test_critic_agent_defaults_to_empty_string(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        assert step.critic_agent == ""

    def test_max_critic_iterations_defaults_to_3(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        assert step.max_critic_iterations == 3


# ---------------------------------------------------------------------------
# models.py — roundtrip
# ---------------------------------------------------------------------------


class TestPlanStepCriticRoundtrip:
    def test_critic_agent_roundtrip(self) -> None:
        step = _task_step(critic_agent="code-reviewer")
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.critic_agent == "code-reviewer"
        assert restored.max_critic_iterations == 3

    def test_max_critic_iterations_roundtrip(self) -> None:
        step = _task_step(critic_agent="security-auditor", max_critic_iterations=5)
        restored = PlanStep.from_dict(step.to_dict())
        assert restored.critic_agent == "security-auditor"
        assert restored.max_critic_iterations == 5

    def test_plan_roundtrip_with_critic_fields(self) -> None:
        plan = _single_step_plan(_task_step(critic_agent="reviewer", max_critic_iterations=2))
        restored = Plan.from_dict(plan.to_dict())
        assert restored.steps[0].critic_agent == "reviewer"
        assert restored.steps[0].max_critic_iterations == 2


# ---------------------------------------------------------------------------
# models.py — sparse serialization
# ---------------------------------------------------------------------------


class TestPlanStepCriticSparseSerialization:
    def test_critic_agent_omitted_when_empty(self) -> None:
        step = _task_step(critic_agent="")
        d = step.to_dict()
        assert "critic_agent" not in d

    def test_max_critic_iterations_omitted_at_default(self) -> None:
        step = _task_step(critic_agent="reviewer", max_critic_iterations=3)
        d = step.to_dict()
        assert "max_critic_iterations" not in d

    def test_critic_agent_present_when_set(self) -> None:
        step = _task_step(critic_agent="security-auditor")
        d = step.to_dict()
        assert d["critic_agent"] == "security-auditor"

    def test_max_critic_iterations_present_when_non_default(self) -> None:
        step = _task_step(critic_agent="reviewer", max_critic_iterations=7)
        d = step.to_dict()
        assert d["max_critic_iterations"] == 7

    def test_both_omitted_on_all_defaults(self) -> None:
        step = _task_step()
        d = step.to_dict()
        assert "critic_agent" not in d
        assert "max_critic_iterations" not in d


# ---------------------------------------------------------------------------
# models.py — backward compatibility (from_dict with missing keys)
# ---------------------------------------------------------------------------


class TestPlanStepCriticBackwardCompat:
    def test_missing_critic_agent_defaults_to_empty(self) -> None:
        old = {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"}
        step = PlanStep.from_dict(old)
        assert step.critic_agent == ""

    def test_missing_max_critic_iterations_defaults_to_3(self) -> None:
        old = {"id": "s1", "type": "task", "prompt": "p", "agent_type": "w"}
        step = PlanStep.from_dict(old)
        assert step.max_critic_iterations == 3

    def test_explicit_max_critic_iterations_in_dict_is_preserved(self) -> None:
        d = {
            "id": "s1",
            "type": "task",
            "prompt": "p",
            "agent_type": "w",
            "critic_agent": "qa-agent",
            "max_critic_iterations": 10,
        }
        step = PlanStep.from_dict(d)
        assert step.critic_agent == "qa-agent"
        assert step.max_critic_iterations == 10


# ---------------------------------------------------------------------------
# parser.py — validation rules
# ---------------------------------------------------------------------------


class TestValidatePlanCriticRules:
    def test_critic_agent_on_task_step_is_valid(self) -> None:
        plan = _single_step_plan(_task_step(critic_agent="code-reviewer"))
        errors = validate_plan(plan)
        critic_errors = [e for e in errors if "critic_agent" in e and "only be set on task" in e]
        assert critic_errors == []

    def test_critic_agent_on_checkpoint_step_is_error(self) -> None:
        step = PlanStep(id="cp", type="checkpoint", prompt="review", critic_agent="reviewer")
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any("critic_agent can only be set on task steps" in e for e in errors)

    def test_critic_agent_on_loop_step_is_error(self) -> None:
        from swarm.plan.models import LoopConfig
        step = PlanStep(
            id="lp",
            type="loop",
            prompt="iterate",
            loop_config=LoopConfig(condition="done"),
            critic_agent="reviewer",
        )
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any("critic_agent can only be set on task steps" in e for e in errors)

    def test_max_critic_iterations_zero_is_error(self) -> None:
        step = _task_step(critic_agent="reviewer", max_critic_iterations=0)
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any("max_critic_iterations must be >= 1" in e for e in errors)

    def test_max_critic_iterations_negative_is_error(self) -> None:
        step = _task_step(critic_agent="reviewer", max_critic_iterations=-5)
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any("max_critic_iterations must be >= 1" in e for e in errors)

    def test_max_critic_iterations_one_is_valid(self) -> None:
        step = _task_step(critic_agent="reviewer", max_critic_iterations=1)
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        iteration_errors = [e for e in errors if "max_critic_iterations must be >= 1" in e]
        assert iteration_errors == []

    def test_max_critic_iterations_without_critic_agent_is_warning(self) -> None:
        # Non-default max_critic_iterations with no critic_agent triggers a warning entry.
        step = _task_step(max_critic_iterations=5)
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any(
            "max_critic_iterations set without critic_agent" in e for e in errors
        )

    def test_default_max_critic_iterations_without_critic_agent_no_warning(self) -> None:
        # Default value (3) + no critic_agent → no warning.
        step = _task_step()
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        warning_entries = [e for e in errors if "max_critic_iterations set without critic_agent" in e]
        assert warning_entries == []

    def test_step_id_included_in_error_message(self) -> None:
        step = PlanStep(id="my-step", type="checkpoint", prompt="p", critic_agent="rev")
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        assert any("my-step" in e for e in errors)

    def test_valid_critic_configuration_no_extra_errors(self) -> None:
        step = _task_step(critic_agent="security-auditor", max_critic_iterations=5)
        plan = _single_step_plan(step)
        errors = validate_plan(plan)
        critic_errors = [
            e for e in errors
            if "critic" in e.lower() and "Warning" not in e
        ]
        assert critic_errors == []


# ---------------------------------------------------------------------------
# plan_execute_step — critic payload
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)
    state.registry_api = None


def _basic_plan_with_critic(critic_agent: str = "code-reviewer", max_iter: int = 3) -> dict:  # type: ignore[type-arg]
    return {
        "version": 1,
        "goal": "deliver feature",
        "variables": {},
        "steps": [
            {
                "id": "build",
                "type": "task",
                "prompt": "Build the feature",
                "agent_type": "backend-developer",
                "output_artifact": "impl.md",
                "critic_agent": critic_agent,
                "max_critic_iterations": max_iter,
            }
        ],
    }


class TestPlanExecuteStepCriticPayload:
    def test_critic_key_present_when_critic_agent_set(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_with_critic())
        result = json.loads(plan_execute_step(str(path), "build"))
        assert "critic" in result

    def test_critic_key_absent_when_no_critic_agent(self, tmp_path: Path) -> None:
        plan_data = {
            "version": 1,
            "goal": "g",
            "variables": {},
            "steps": [
                {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"}
            ],
        }
        path = _write_plan(tmp_path, plan_data)
        result = json.loads(plan_execute_step(str(path), "s1"))
        assert "critic" not in result

    def test_critic_block_has_agent_type(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_with_critic("security-auditor"))
        result = json.loads(plan_execute_step(str(path), "build"))
        assert result["critic"]["agent_type"] == "security-auditor"

    def test_critic_block_has_max_iterations(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_with_critic(max_iter=7))
        result = json.loads(plan_execute_step(str(path), "build"))
        assert result["critic"]["max_iterations"] == 7

    def test_critic_block_max_iterations_default_3(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_with_critic())
        result = json.loads(plan_execute_step(str(path), "build"))
        assert result["critic"]["max_iterations"] == 3

    def test_primary_agent_fields_still_present_with_critic(self, tmp_path: Path) -> None:
        path = _write_plan(tmp_path, _basic_plan_with_critic())
        result = json.loads(plan_execute_step(str(path), "build"))
        assert result["agent_type"] == "backend-developer"
        assert result["prompt"] == "Build the feature"
        assert result["output_artifact"] == "impl.md"

    def test_critic_description_absent_without_registry(self, tmp_path: Path) -> None:
        state.registry_api = None
        path = _write_plan(tmp_path, _basic_plan_with_critic())
        result = json.loads(plan_execute_step(str(path), "build"))
        assert "description" not in result["critic"]

    def test_critic_description_resolved_from_registry(self, tmp_path: Path) -> None:
        mock_api = MagicMock()

        def _resolve(name: str) -> AgentDefinition:
            agents = {
                "backend-developer": AgentDefinition(
                    id="a1", name="backend-developer",
                    system_prompt="", description="Backend dev agent",
                ),
                "code-reviewer": AgentDefinition(
                    id="a2", name="code-reviewer",
                    system_prompt="", description="Reviews code thoroughly",
                ),
            }
            if name not in agents:
                raise RegistryError("not found")
            return agents[name]

        mock_api.resolve_agent.side_effect = _resolve
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_with_critic("code-reviewer"))
        result = json.loads(plan_execute_step(str(path), "build"))

        assert result["critic"]["description"] == "Reviews code thoroughly"
        # Primary agent description also resolved
        assert result["description"] == "Backend dev agent"

    def test_critic_description_absent_when_registry_raises(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.side_effect = RegistryError("not found")
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_with_critic("unknown-critic"))
        result = json.loads(plan_execute_step(str(path), "build"))

        assert "critic" in result
        assert result["critic"]["agent_type"] == "unknown-critic"
        assert "description" not in result["critic"]

    def test_critic_registry_failure_does_not_affect_primary_resolution(
        self, tmp_path: Path
    ) -> None:
        mock_api = MagicMock()

        call_count = 0

        def _selective_resolve(name: str) -> AgentDefinition:
            nonlocal call_count
            call_count += 1
            if name == "backend-developer":
                return AgentDefinition(
                    id="a1", name="backend-developer",
                    system_prompt="", description="Primary agent",
                )
            raise RegistryError("critic not in registry")

        mock_api.resolve_agent.side_effect = _selective_resolve
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_with_critic("missing-critic"))
        result = json.loads(plan_execute_step(str(path), "build"))

        assert result["description"] == "Primary agent"
        assert "critic" in result
        assert result["critic"]["agent_type"] == "missing-critic"
        assert "description" not in result["critic"]

    def test_registry_resolve_called_for_both_agents(self, tmp_path: Path) -> None:
        mock_api = MagicMock()
        mock_api.resolve_agent.side_effect = RegistryError("not found")
        state.registry_api = mock_api

        path = _write_plan(tmp_path, _basic_plan_with_critic("code-reviewer"))
        plan_execute_step(str(path), "build")

        calls = [c.args[0] for c in mock_api.resolve_agent.call_args_list]
        assert "backend-developer" in calls
        assert "code-reviewer" in calls
