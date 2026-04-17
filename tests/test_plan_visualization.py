"""Tests for swarm.plan.visualization: render_mermaid and render_ascii."""

from __future__ import annotations

import json

import pytest

from swarm.mcp import state
from swarm.mcp.plan_tools import plan_visualize
from swarm.plan.models import (
    FanOutBranch,
    FanOutConfig,
    Plan,
    PlanStep,
)
from swarm.plan.visualization import render_ascii, render_mermaid


def _plan(*steps: PlanStep) -> Plan:
    return Plan(version=1, goal="test", steps=list(steps))


# ---------------------------------------------------------------------------
# render_mermaid tests
# ---------------------------------------------------------------------------


class TestRenderMermaid:
    def test_single_step_produces_flowchart(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="worker"))
        result = render_mermaid(plan)
        assert result.startswith("flowchart TD")
        assert 's1["s1 | worker"]' in result

    def test_two_step_chain_has_edge(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="writer"),
            PlanStep(id="b", type="task", prompt="p", agent_type="reviewer", depends_on=("a",)),
        )
        result = render_mermaid(plan)
        assert "a --> b" in result

    def test_diamond_dag_edges(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="d", type="task", prompt="p", agent_type="w", depends_on=("b", "c")),
        )
        result = render_mermaid(plan)
        assert "a --> b" in result
        assert "a --> c" in result
        assert "b --> d" in result
        assert "c --> d" in result

    def test_completed_step_green(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_mermaid(plan, completed={"s1"})
        assert "fill:#28a745" in result  # green

    def test_failed_step_red(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_mermaid(plan, step_outcomes={"s1": "failed"})
        assert "fill:#dc3545" in result  # red

    def test_ready_step_yellow(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_mermaid(plan)
        assert "fill:#ffc107" in result  # yellow — ready, no deps

    def test_blocked_step_gray(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        result = render_mermaid(plan)
        # b is blocked (a not completed); a is ready
        lines = result.split("\n")
        b_style = [line for line in lines if line.strip().startswith("style b")]
        assert any("fill:#6c757d" in line for line in b_style)

    def test_checkpoint_step_blue(self) -> None:
        plan = _plan(
            PlanStep(id="chk", type="checkpoint", prompt="pause"),
        )
        result = render_mermaid(plan)
        assert "fill:#007bff" in result  # blue — checkpoint

    def test_checkpoint_blocked_gray(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="chk", type="checkpoint", prompt="pause", depends_on=("a",)),
        )
        result = render_mermaid(plan)
        # chk is blocked because a is not completed
        lines = result.split("\n")
        chk_style = [line for line in lines if line.strip().startswith("style chk")]
        assert any("fill:#6c757d" in line for line in chk_style)

    def test_condition_label_on_edge(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(
                id="b",
                type="task",
                prompt="p",
                agent_type="w",
                depends_on=("a",),
                condition="step_failed:a",
            ),
        )
        result = render_mermaid(plan)
        assert "-->|step_failed:a|" in result

    def test_fan_out_branches_rendered(self) -> None:
        cfg = FanOutConfig(branches=(
            FanOutBranch(agent_type="alpha", prompt="do alpha"),
            FanOutBranch(agent_type="beta", prompt="do beta"),
        ))
        plan = _plan(
            PlanStep(id="fo", type="fan_out", prompt="", fan_out_config=cfg),
        )
        result = render_mermaid(plan)
        assert "fo_b0" in result
        assert "fo_b1" in result
        assert "fo --> fo_b0" in result
        assert "fo --> fo_b1" in result
        assert "alpha" in result
        assert "beta" in result

    def test_critic_loop_annotation(self) -> None:
        plan = _plan(
            PlanStep(
                id="s1",
                type="task",
                prompt="p",
                agent_type="w",
                critic_agent="reviewer",
            ),
        )
        result = render_mermaid(plan)
        assert "critic: reviewer" in result
        assert "-.>" in result or ".->" in result

    def test_no_agent_type_label(self) -> None:
        plan = _plan(PlanStep(id="chk", type="checkpoint", prompt="pause"))
        result = render_mermaid(plan)
        # Label should just be the ID, no pipe separator
        assert 'chk["chk"]' in result

    def test_none_completed_treated_as_empty(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_mermaid(plan, completed=None, step_outcomes=None)
        assert "flowchart TD" in result

    def test_hyphenated_id_sanitized(self) -> None:
        plan = _plan(
            PlanStep(id="step-1", type="task", prompt="p", agent_type="w"),
            PlanStep(id="step-2", type="task", prompt="p", agent_type="w", depends_on=("step-1",)),
        )
        result = render_mermaid(plan)
        # Hyphens converted to underscores for Mermaid node IDs
        assert "step_1" in result
        assert "step_2" in result
        assert "step_1 --> step_2" in result
        # Label still shows original ID
        assert "step-1" in result
        assert "step-2" in result


# ---------------------------------------------------------------------------
# render_ascii tests
# ---------------------------------------------------------------------------


class TestRenderAscii:
    def test_single_step_one_wave(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="worker"))
        result = render_ascii(plan)
        lines = result.strip().split("\n")
        # Header + separator + 1 data row
        assert len(lines) == 3
        assert "Wave" in lines[0]
        assert "s1" in lines[2]
        assert "worker" in lines[2]

    def test_two_independent_steps_same_wave(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w1"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w2"),
        )
        result = render_ascii(plan)
        lines = result.strip().split("\n")
        data_lines = lines[2:]  # skip header + separator
        # Both should be wave 0
        for line in data_lines:
            assert line.strip().startswith("0")

    def test_chain_multiple_waves(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("b",)),
        )
        result = render_ascii(plan)
        lines = result.strip().split("\n")
        data_lines = lines[2:]
        # Should be waves 0, 1, 2
        assert len(data_lines) == 3
        wave_numbers = [line.strip()[0] for line in data_lines]
        assert wave_numbers == ["0", "1", "2"]

    def test_diamond_two_steps_same_wave(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="c", type="task", prompt="p", agent_type="w", depends_on=("a",)),
            PlanStep(id="d", type="task", prompt="p", agent_type="w", depends_on=("b", "c")),
        )
        result = render_ascii(plan)
        lines = result.strip().split("\n")
        data_lines = lines[2:]
        # 4 steps: wave 0 (a), wave 1 (b, c), wave 2 (d)
        assert len(data_lines) == 4

    def test_completed_symbol(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_ascii(plan, completed={"s1"})
        assert "\u2713" in result

    def test_failed_symbol(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_ascii(plan, step_outcomes={"s1": "failed"})
        assert "\u2717" in result

    def test_ready_symbol(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_ascii(plan)
        assert "\u2192" in result  # arrow = ready

    def test_blocked_symbol(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        result = render_ascii(plan)
        assert "\u00b7" in result  # dot = blocked

    def test_depends_on_shown_inline(self) -> None:
        plan = _plan(
            PlanStep(id="a", type="task", prompt="p", agent_type="w"),
            PlanStep(id="b", type="task", prompt="p", agent_type="w", depends_on=("a",)),
        )
        result = render_ascii(plan)
        # The b row should show "a" in depends column
        lines = result.strip().split("\n")
        b_line = [
            line for line in lines
            if "  b  " in line or line.strip().startswith("1")
        ][0]
        assert "a" in b_line

    def test_no_deps_shown_as_dash(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_ascii(plan)
        lines = result.strip().split("\n")
        data_line = lines[2]
        assert "-" in data_line

    def test_checkpoint_type_used_when_no_agent(self) -> None:
        plan = _plan(PlanStep(id="chk", type="checkpoint", prompt="pause"))
        result = render_ascii(plan)
        assert "checkpoint" in result

    def test_none_completed_treated_as_empty(self) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p", agent_type="w"))
        result = render_ascii(plan, completed=None, step_outcomes=None)
        assert "Wave" in result


# ---------------------------------------------------------------------------
# plan_visualize MCP tool tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    state.registry_api = None


def _basic_plan_json() -> str:
    return json.dumps({
        "version": 1,
        "goal": "test",
        "steps": [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "reviewer", "depends_on": ["s1"]},
        ],
    })


class TestPlanVisualize:
    def test_mermaid_format(self) -> None:
        result = json.loads(plan_visualize(_basic_plan_json()))
        assert result["format"] == "mermaid"
        assert "flowchart TD" in result["diagram"]
        assert "worker" in result["diagram"]

    def test_ascii_format(self) -> None:
        result = json.loads(plan_visualize(_basic_plan_json(), format="ascii"))
        assert result["format"] == "ascii"
        assert "Wave" in result["diagram"]
        assert "worker" in result["diagram"]

    def test_unknown_format_error(self) -> None:
        result = json.loads(plan_visualize(_basic_plan_json(), format="svg"))
        assert "error" in result
        assert "svg" in result["error"]

    def test_with_completed_steps(self) -> None:
        result = json.loads(
            plan_visualize(_basic_plan_json(), completed_json='["s1"]')
        )
        assert result["format"] == "mermaid"
        assert "fill:#28a745" in result["diagram"]  # green for completed

    def test_with_step_outcomes(self) -> None:
        result = json.loads(
            plan_visualize(
                _basic_plan_json(),
                step_outcomes_json='{"s1": "failed"}',
            )
        )
        assert "fill:#dc3545" in result["diagram"]  # red for failed

    def test_invalid_plan_json(self) -> None:
        result = json.loads(plan_visualize("{not valid"))
        assert "error" in result
        assert "Invalid plan_json" in result["error"]

    def test_invalid_completed_json(self) -> None:
        result = json.loads(plan_visualize(_basic_plan_json(), completed_json="{bad"))
        assert "error" in result
        assert "Invalid completed_json" in result["error"]

    def test_invalid_step_outcomes_json(self) -> None:
        result = json.loads(
            plan_visualize(_basic_plan_json(), step_outcomes_json="{bad")
        )
        assert "error" in result
        assert "Invalid step_outcomes_json" in result["error"]

    def test_format_case_insensitive(self) -> None:
        result = json.loads(plan_visualize(_basic_plan_json(), format="MERMAID"))
        assert result["format"] == "mermaid"
        assert "flowchart TD" in result["diagram"]

    def test_ascii_with_completed(self) -> None:
        result = json.loads(
            plan_visualize(
                _basic_plan_json(),
                completed_json='["s1"]',
                format="ascii",
            )
        )
        assert result["format"] == "ascii"
        assert "\u2713" in result["diagram"]

    def test_empty_plan_steps(self) -> None:
        plan_json = json.dumps({"version": 1, "goal": "empty", "steps": []})
        result = json.loads(plan_visualize(plan_json))
        assert result["format"] == "mermaid"
        assert "flowchart TD" in result["diagram"]
