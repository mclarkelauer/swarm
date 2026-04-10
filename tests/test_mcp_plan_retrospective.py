"""Tests for the plan_retrospective MCP tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.plan_tools import plan_retrospective
from swarm.plan.run_log import RunLog, StepOutcome, write_run_log

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)


def _write_plan(tmp_path: Path, plan_data: dict) -> Path:  # type: ignore[type-arg]
    """Write a plan dict to plan_v1.json and return its path."""
    path = tmp_path / "plan_v1.json"
    path.write_text(json.dumps(plan_data), encoding="utf-8")
    return path


def _write_run_log(tmp_path: Path, log: RunLog, name: str = "run_log.json") -> Path:
    """Write a RunLog to a file and return its path."""
    path = tmp_path / name
    write_run_log(log, path)
    return path


def _basic_plan_data(steps: list | None = None) -> dict:  # type: ignore[type-arg]
    """Return a minimal plan dict with configurable steps."""
    if steps is None:
        steps = [
            {"id": "s1", "type": "task", "prompt": "do thing one", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "do thing two", "agent_type": "analyst", "depends_on": ["s1"]},
            {"id": "s3", "type": "task", "prompt": "do thing three", "agent_type": "worker", "depends_on": ["s2"]},
        ]
    return {"version": 1, "goal": "test retrospective", "steps": steps}


def _make_outcome(
    step_id: str,
    status: str = "completed",
    started_at: str = "2026-01-01T00:00:00",
    finished_at: str = "2026-01-01T00:00:10",
) -> StepOutcome:
    return StepOutcome(
        step_id=step_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
    )


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveErrors:
    def test_missing_run_log_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(plan_retrospective(str(tmp_path / "nonexistent.json")))
        assert "error" in result
        assert "Run log not found" in result["error"]

    def test_missing_plan_file_returns_error(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path=str(tmp_path / "missing_plan.json"),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        assert "error" in result
        assert "Plan file not found" in result["error"]

    def test_plan_path_arg_overrides_log_plan_path(self, tmp_path: Path) -> None:
        # Log has a bad plan_path; explicit plan_path arg should take over.
        log = RunLog(
            plan_path="/nonexistent/bad_plan.json",
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[],
        )
        log_path = _write_run_log(tmp_path, log)
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        result = json.loads(plan_retrospective(str(log_path), plan_path=str(plan_path)))
        # Should succeed — no error key
        assert "error" not in result

    def test_empty_plan_path_with_no_log_plan_path_returns_error(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="",
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path), plan_path=""))
        assert "error" in result


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveHappyPath:
    def test_aggregate_counts(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:05"),
                _make_outcome("s2", "failed",    "2026-01-01T00:00:05", "2026-01-01T00:00:07"),
                _make_outcome("s3", "skipped",   "2026-01-01T00:00:07", "2026-01-01T00:00:07"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert result["total_steps"] == 3
        assert result["completed"] == 1
        assert result["failed"] == 1
        assert result["skipped"] == 1

    def test_total_steps_from_plan_not_log(self, tmp_path: Path) -> None:
        # Plan has 3 steps but only 2 appear in the run log (one was never started).
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
                # s3 never ran
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        # total_steps reflects the plan (3), not the log (2)
        assert result["total_steps"] == 3
        assert result["completed"] == 2

    def test_response_shape(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[_make_outcome("s1", "completed")],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        required_keys = {
            "total_steps", "completed", "failed", "skipped",
            "slowest_steps", "failing_agents", "unused_artifacts", "suggestions",
            "cost_summary",
        }
        assert required_keys.issubset(result.keys())
        assert "total_tokens" in result["cost_summary"]
        assert "total_cost_usd" in result["cost_summary"]


# ---------------------------------------------------------------------------
# Empty run log
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveEmptyRunLog:
    def test_empty_run_log(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert result["total_steps"] == 3
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert result["slowest_steps"] == []
        assert result["failing_agents"] == []
        assert result["suggestions"] == []
        assert result["cost_summary"]["total_tokens"] == 0
        assert result["cost_summary"]["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# Cost summary
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveCostSummary:
    def test_sums_tokens_and_cost_across_steps(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                StepOutcome(
                    step_id="s1", status="completed",
                    started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:00:05",
                    tokens_used=1000, cost_usd=0.01, model="claude-3",
                ),
                StepOutcome(
                    step_id="s2", status="completed",
                    started_at="2026-01-01T00:00:05", finished_at="2026-01-01T00:00:10",
                    tokens_used=2000, cost_usd=0.02, model="claude-3",
                ),
                StepOutcome(
                    step_id="s3", status="failed",
                    started_at="2026-01-01T00:00:10", finished_at="2026-01-01T00:00:12",
                    tokens_used=500, cost_usd=0.005,
                ),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        cost = result["cost_summary"]
        assert cost["total_tokens"] == 3500
        assert cost["total_cost_usd"] == pytest.approx(0.035)
        # per_step only includes steps with tokens_used > 0
        assert len(cost["per_step"]) == 3
        assert cost["per_step"][0]["step_id"] == "s1"
        assert cost["per_step"][0]["tokens"] == 1000
        assert cost["per_step"][0]["model"] == "claude-3"

    def test_zero_cost_when_no_tracking_data(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        cost = result["cost_summary"]
        assert cost["total_tokens"] == 0
        assert cost["total_cost_usd"] == 0.0
        assert cost["per_step"] == []


# ---------------------------------------------------------------------------
# All-success run — no failure suggestions
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveAllSuccess:
    def test_no_failure_suggestions_when_all_succeed(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:05"),
                _make_outcome("s2", "completed", "2026-01-01T00:00:05", "2026-01-01T00:00:10"),
                _make_outcome("s3", "completed", "2026-01-01T00:00:10", "2026-01-01T00:00:15"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert result["failed"] == 0
        assert result["failing_agents"] == []
        # No "failed" or "time(s)" style suggestions
        failure_suggestions = [s for s in result["suggestions"] if "failed" in s]
        assert failure_suggestions == []


# ---------------------------------------------------------------------------
# Steps without timestamps
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveNoTimestamps:
    def test_missing_timestamps_treated_as_none(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                StepOutcome(step_id="s1", status="completed", started_at="", finished_at=""),
                StepOutcome(step_id="s2", status="completed", started_at="", finished_at=""),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        # Should not raise; steps with no timestamps simply have no duration
        result = json.loads(plan_retrospective(str(log_path)))
        assert "error" not in result
        assert result["slowest_steps"] == []

    def test_invalid_timestamp_strings_treated_as_none(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                StepOutcome(
                    step_id="s1", status="completed",
                    started_at="not-a-date", finished_at="also-not-a-date",
                ),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        assert "error" not in result
        assert result["slowest_steps"] == []

    def test_mixed_timestamps_only_valid_steps_appear_in_slowest(self, tmp_path: Path) -> None:
        plan_path = _write_plan(tmp_path, _basic_plan_data())
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:30"),
                StepOutcome(step_id="s2", status="completed", started_at="", finished_at=""),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        # Only s1 has a valid duration
        assert len(result["slowest_steps"]) == 1
        assert result["slowest_steps"][0]["id"] == "s1"


# ---------------------------------------------------------------------------
# Slowest step detection
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveSlowestSteps:
    def test_returns_top_3_slowest(self, tmp_path: Path) -> None:
        steps = [
            {"id": f"s{i}", "type": "task", "prompt": f"step {i}", "agent_type": "worker"}
            for i in range(1, 6)
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        # Durations: s1=5s, s2=60s, s3=10s, s4=120s, s5=30s
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:05"),
                _make_outcome("s2", "completed", "2026-01-01T00:00:05", "2026-01-01T00:01:05"),
                _make_outcome("s3", "completed", "2026-01-01T00:01:05", "2026-01-01T00:01:15"),
                _make_outcome("s4", "completed", "2026-01-01T00:01:15", "2026-01-01T00:03:15"),
                _make_outcome("s5", "completed", "2026-01-01T00:03:15", "2026-01-01T00:03:45"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        slowest = result["slowest_steps"]
        assert len(slowest) == 3
        # Top 3 by descending duration: s4(120), s2(60), s5(30)
        assert slowest[0]["id"] == "s4"
        assert slowest[0]["duration_s"] == pytest.approx(120.0)
        assert slowest[1]["id"] == "s2"
        assert slowest[1]["duration_s"] == pytest.approx(60.0)
        assert slowest[2]["id"] == "s5"
        assert slowest[2]["duration_s"] == pytest.approx(30.0)

    def test_fewer_than_3_steps_returns_all(self, tmp_path: Path) -> None:
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "worker"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:05"),
                _make_outcome("s2", "completed", "2026-01-01T00:00:05", "2026-01-01T00:00:15"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        assert len(result["slowest_steps"]) == 2

    def test_slowest_step_includes_agent_type(self, tmp_path: Path) -> None:
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "code-reviewer"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:01:00"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        assert result["slowest_steps"][0]["agent_type"] == "code-reviewer"

    def test_slow_step_suggestion_generated(self, tmp_path: Path) -> None:
        # s1 takes 100s, s2 takes 5s, s3 takes 5s → avg ~36.7s → s1 > 2x avg
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s3", "type": "task", "prompt": "p", "agent_type": "worker"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:01:40"),
                _make_outcome("s2", "completed", "2026-01-01T00:01:40", "2026-01-01T00:01:45"),
                _make_outcome("s3", "completed", "2026-01-01T00:01:45", "2026-01-01T00:01:50"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        slow_suggestions = [s for s in result["suggestions"] if "Consider splitting" in s]
        assert len(slow_suggestions) == 1
        assert "s1" in slow_suggestions[0]

    def test_no_slow_step_suggestion_when_all_uniform(self, tmp_path: Path) -> None:
        # All steps take the same duration — no step exceeds 2x average
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "worker"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:10"),
                _make_outcome("s2", "completed", "2026-01-01T00:00:10", "2026-01-01T00:00:20"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        slow_suggestions = [s for s in result["suggestions"] if "Consider splitting" in s]
        assert slow_suggestions == []


# ---------------------------------------------------------------------------
# Failing agents
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveFailingAgents:
    def test_groups_failures_by_agent(self, tmp_path: Path) -> None:
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "writer"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "writer"},
            {"id": "s3", "type": "task", "prompt": "p", "agent_type": "analyst"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "failed"),
                _make_outcome("s2", "failed"),
                _make_outcome("s3", "failed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        failing = {entry["agent_type"]: entry for entry in result["failing_agents"]}
        assert failing["writer"]["failures"] == 2
        assert set(failing["writer"]["step_ids"]) == {"s1", "s2"}
        assert failing["analyst"]["failures"] == 1
        assert failing["analyst"]["step_ids"] == ["s3"]

    def test_failing_agent_suggestion_generated(self, tmp_path: Path) -> None:
        steps = [{"id": "s1", "type": "task", "prompt": "p", "agent_type": "flaky-bot"}]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[_make_outcome("s1", "failed")],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))
        agent_suggestions = [s for s in result["suggestions"] if "flaky-bot" in s]
        assert len(agent_suggestions) == 1
        assert "failed 1 time(s)" in agent_suggestions[0]


# ---------------------------------------------------------------------------
# Unused artifact detection
# ---------------------------------------------------------------------------


class TestPlanRetrospectiveUnusedArtifacts:
    def test_detects_unused_artifact(self, tmp_path: Path) -> None:
        steps = [
            {
                "id": "s1", "type": "task", "prompt": "p", "agent_type": "worker",
                "output_artifact": "report.md",
            },
            {
                "id": "s2", "type": "task", "prompt": "p", "agent_type": "worker",
                # Does NOT consume report.md
            },
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert len(result["unused_artifacts"]) == 1
        assert result["unused_artifacts"][0]["path"] == "report.md"
        assert result["unused_artifacts"][0]["step_id"] == "s1"

    def test_no_unused_artifact_when_consumed(self, tmp_path: Path) -> None:
        steps = [
            {
                "id": "s1", "type": "task", "prompt": "p", "agent_type": "worker",
                "output_artifact": "data.json",
            },
            {
                "id": "s2", "type": "task", "prompt": "p", "agent_type": "worker",
                "depends_on": ["s1"],
                "required_inputs": ["data.json"],
            },
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert result["unused_artifacts"] == []

    def test_no_output_artifacts_means_no_unused_report(self, tmp_path: Path) -> None:
        # Plan has no output_artifact fields at all — unused_artifacts should be empty.
        steps = [
            {"id": "s1", "type": "task", "prompt": "p", "agent_type": "worker"},
            {"id": "s2", "type": "task", "prompt": "p", "agent_type": "worker"},
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        assert result["unused_artifacts"] == []

    def test_unused_artifact_suggestion_generated(self, tmp_path: Path) -> None:
        steps = [
            {
                "id": "s1", "type": "task", "prompt": "p", "agent_type": "worker",
                "output_artifact": "debug.txt",
            },
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[_make_outcome("s1", "completed")],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        artifact_suggestions = [s for s in result["suggestions"] if "debug.txt" in s]
        assert len(artifact_suggestions) == 1
        assert "s1" in artifact_suggestions[0]
        assert "no downstream consumer" in artifact_suggestions[0]

    def test_partial_consumption_leaves_unconsumed_flagged(self, tmp_path: Path) -> None:
        # s1 outputs a.txt (consumed by s3), s2 outputs b.txt (not consumed)
        steps = [
            {
                "id": "s1", "type": "task", "prompt": "p", "agent_type": "worker",
                "output_artifact": "a.txt",
            },
            {
                "id": "s2", "type": "task", "prompt": "p", "agent_type": "worker",
                "output_artifact": "b.txt",
            },
            {
                "id": "s3", "type": "task", "prompt": "p", "agent_type": "worker",
                "depends_on": ["s1"],
                "required_inputs": ["a.txt"],
            },
        ]
        plan_path = _write_plan(tmp_path, {"version": 1, "goal": "g", "steps": steps})
        log = RunLog(
            plan_path=str(plan_path),
            plan_version=1,
            started_at="2026-01-01T00:00:00",
            steps=[
                _make_outcome("s1", "completed"),
                _make_outcome("s2", "completed"),
                _make_outcome("s3", "completed"),
            ],
        )
        log_path = _write_run_log(tmp_path, log)
        result = json.loads(plan_retrospective(str(log_path)))

        unused_paths = {ua["path"] for ua in result["unused_artifacts"]}
        assert "b.txt" in unused_paths
        assert "a.txt" not in unused_paths
