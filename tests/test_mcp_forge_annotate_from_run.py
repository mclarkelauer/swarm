"""Tests for forge_annotate_from_run MCP tool."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.forge.api import ForgeAPI
from swarm.mcp import state
from swarm.mcp.forge_tools import forge_annotate_from_run, forge_create
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, StepOutcome, write_run_log
from swarm.registry.api import RegistryAPI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(tmp_path: Path, steps: list[PlanStep], goal: str = "test goal") -> Path:
    """Serialize a Plan to JSON and return its path."""
    plan = Plan(version=1, goal=goal, steps=steps)
    plan_file = tmp_path / "plan_v1.json"
    plan_file.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return plan_file


def _make_run_log(tmp_path: Path, plan_path: Path, outcomes: list[StepOutcome]) -> Path:
    """Write a RunLog with the given outcomes and return its path."""
    log = RunLog(
        plan_path=str(plan_path),
        plan_version=1,
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T01:00:00",
        status="completed",
        steps=outcomes,
    )
    log_file = tmp_path / "run_log.json"
    write_run_log(log, log_file)
    return log_file


def _step(step_id: str, agent_type: str) -> PlanStep:
    return PlanStep(id=step_id, type="task", prompt=f"Do {step_id}", agent_type=agent_type)


def _outcome(step_id: str, status: str, message: str = "") -> StepOutcome:
    return StepOutcome(
        step_id=step_id,
        status=status,
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:01:00",
        message=message,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> Iterator[None]:
    db = tmp_path / "registry.db"
    state.registry_api = RegistryAPI(db)
    state.forge_api = ForgeAPI(db, tmp_path / "forge")
    try:
        yield
    finally:
        assert state.registry_api is not None
        state.registry_api.close()
        assert state.forge_api is not None
        state.forge_api.close()
        state.registry_api = None
        state.forge_api = None


# ---------------------------------------------------------------------------
# Happy path — mixed outcomes
# ---------------------------------------------------------------------------

class TestAnnotateFromRunMixedOutcomes:
    def test_annotated_list_contains_expected_agents(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")
        forge_create("reviewer", "Reviews code.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "coder"),
            _step("s2", "coder"),
            _step("s3", "reviewer"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "failed", "timeout"),
            _outcome("s3", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert "error" not in result
        names = {a["name"] for a in result["annotated"]}
        assert names == {"coder", "reviewer"}
        assert result["unchanged"] == []
        assert result["skipped"] == []

    def test_coder_usage_and_failure_delta(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")
        forge_create("reviewer", "Reviews code.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "coder"),
            _step("s2", "coder"),
            _step("s3", "reviewer"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "failed", "timeout"),
            _outcome("s3", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        coder_entry = next(a for a in result["annotated"] if a["name"] == "coder")
        assert coder_entry["usage_delta"] == 2
        assert coder_entry["failure_delta"] == 1

    def test_reviewer_has_no_failure_delta(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")
        forge_create("reviewer", "Reviews code.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "coder"),
            _step("s2", "coder"),
            _step("s3", "reviewer"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "failed", "timeout"),
            _outcome("s3", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        reviewer_entry = next(a for a in result["annotated"] if a["name"] == "reviewer")
        assert reviewer_entry["usage_delta"] == 1
        assert reviewer_entry["failure_delta"] == 0

    def test_cloned_agent_has_updated_usage_count(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder"), _step("s2", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert cloned.usage_count == 2

    def test_cloned_agent_failure_appended_to_notes(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.", notes="initial note")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "failed", "out of memory"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert "initial note" in cloned.notes
        assert "Run annotation:" in cloned.notes
        assert "s1" in cloned.notes
        assert "out of memory" in cloned.notes

    def test_cloned_agent_has_last_used_set(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert cloned.last_used != ""

    def test_new_id_is_different_from_original(self, tmp_path: Path) -> None:
        created = json.loads(forge_create("coder", "Writes code."))
        original_id = created["id"]

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert result["annotated"][0]["new_id"] != original_id

    def test_plan_path_from_run_log_used_when_not_provided(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        # Do NOT pass plan_path — it should be read from the run log
        result = json.loads(forge_annotate_from_run(str(log_file)))
        assert "error" not in result
        assert len(result["annotated"]) == 1

    def test_explicit_plan_path_overrides_log_plan_path(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        # Write a run log that points to a non-existent plan
        log = RunLog(
            plan_path="/nonexistent/path.json",
            plan_version=1,
            started_at="t0",
            steps=[_outcome("s1", "completed")],
        )
        log_file = tmp_path / "run_log.json"
        write_run_log(log, log_file)

        result = json.loads(forge_annotate_from_run(str(log_file), plan_path=str(plan_file)))
        assert "error" not in result
        assert len(result["annotated"]) == 1


# ---------------------------------------------------------------------------
# All-success agents
# ---------------------------------------------------------------------------

class TestAnnotateFromRunAllSuccess:
    def test_no_failures_no_notes_update(self, tmp_path: Path) -> None:
        forge_create("writer", "Writes docs.", notes="keep this")

        plan_file = _make_plan(tmp_path, [_step("s1", "writer"), _step("s2", "writer")])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        # Notes should not have "Run annotation:" appended on success
        assert "Run annotation:" not in cloned.notes
        assert cloned.notes == "keep this"

    def test_failure_count_not_incremented_on_all_success(self, tmp_path: Path) -> None:
        forge_create("writer", "Writes docs.")

        plan_file = _make_plan(tmp_path, [_step("s1", "writer")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert cloned.failure_count == 0

    def test_usage_count_accumulates_across_runs(self, tmp_path: Path) -> None:
        """Second annotation on top of a previously annotated agent."""
        forge_create("writer", "Writes docs.")

        plan_file = _make_plan(tmp_path, [_step("s1", "writer")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        # First run
        json.loads(forge_annotate_from_run(str(log_file)))

        # Create a second run log pointing at the same plan
        log2 = RunLog(
            plan_path=str(plan_file),
            plan_version=1,
            started_at="t0",
            steps=[_outcome("s1", "completed")],
        )
        log_file2 = tmp_path / "run_log2.json"
        write_run_log(log2, log_file2)

        # The second annotation resolves the *first clone* (usage_count=1) by name
        result2 = json.loads(forge_annotate_from_run(str(log_file2)))

        assert state.registry_api is not None
        second_new_id = result2["annotated"][0]["new_id"]
        second_clone = state.registry_api.get(second_new_id)
        assert second_clone is not None
        # The clone chain should show accumulated usage
        assert second_clone.usage_count >= 1


# ---------------------------------------------------------------------------
# Agents not in registry
# ---------------------------------------------------------------------------

class TestAnnotateFromRunAgentNotInRegistry:
    def test_unknown_agent_goes_to_skipped(self, tmp_path: Path) -> None:
        # Do NOT register "phantom-agent"
        plan_file = _make_plan(tmp_path, [_step("s1", "phantom-agent")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert result["annotated"] == []
        assert result["unchanged"] == []
        assert result["skipped"] == ["phantom-agent"]

    def test_mix_of_known_and_unknown_agents(self, tmp_path: Path) -> None:
        forge_create("known-agent", "Does known things.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "known-agent"),
            _step("s2", "unknown-agent"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s2", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert len(result["annotated"]) == 1
        assert result["annotated"][0]["name"] == "known-agent"
        assert result["skipped"] == ["unknown-agent"]
        assert result["unchanged"] == []


# ---------------------------------------------------------------------------
# Empty run log
# ---------------------------------------------------------------------------

class TestAnnotateFromRunEmptyLog:
    def test_empty_steps_all_agents_unchanged(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [])  # no steps

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert result["annotated"] == []
        assert result["unchanged"] == ["coder"]
        assert result["skipped"] == []

    def test_empty_steps_multiple_agents_all_unchanged(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")
        forge_create("reviewer", "Reviews code.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "coder"),
            _step("s2", "reviewer"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert result["annotated"] == []
        assert sorted(result["unchanged"]) == ["coder", "reviewer"]
        assert result["skipped"] == []


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestAnnotateFromRunErrors:
    def test_missing_run_log_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(forge_annotate_from_run(str(tmp_path / "nonexistent.json")))
        assert "error" in result
        assert "Run log not found" in result["error"]

    def test_missing_plan_file_returns_error(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path=str(tmp_path / "ghost_plan.json"),
            plan_version=1,
            started_at="t0",
            steps=[],
        )
        log_file = tmp_path / "run_log.json"
        write_run_log(log, log_file)

        result = json.loads(forge_annotate_from_run(str(log_file)))
        assert "error" in result
        assert "Plan not found" in result["error"]

    def test_explicit_missing_plan_returns_error(self, tmp_path: Path) -> None:
        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [])

        result = json.loads(forge_annotate_from_run(
            str(log_file),
            plan_path=str(tmp_path / "no_such_plan.json"),
        ))
        assert "error" in result
        assert "Plan not found" in result["error"]

    def test_run_log_no_plan_path_and_none_provided(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="",
            plan_version=1,
            started_at="t0",
            steps=[],
        )
        log_file = tmp_path / "run_log.json"
        write_run_log(log, log_file)

        result = json.loads(forge_annotate_from_run(str(log_file)))
        assert "error" in result
        assert "plan_path" in result["error"]

    def test_steps_not_in_plan_are_ignored(self, tmp_path: Path) -> None:
        """Outcomes for step_ids absent from the plan are silently ignored."""
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        # Include an outcome for step "s99" which is not in the plan
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "completed"),
            _outcome("s99", "completed"),  # not in plan
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))
        assert "error" not in result
        assert result["annotated"][0]["usage_delta"] == 1  # only s1 counted

    def test_plan_steps_without_agent_type_are_ignored(self, tmp_path: Path) -> None:
        """Checkpoint/join steps with no agent_type do not appear in any list."""
        plan_file = _make_plan(tmp_path, [
            PlanStep(id="chk1", type="checkpoint", prompt="Check progress"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("chk1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))
        assert "error" not in result
        assert result["annotated"] == []
        assert result["unchanged"] == []
        assert result["skipped"] == []


# ---------------------------------------------------------------------------
# Provenance / clone chain
# ---------------------------------------------------------------------------

class TestAnnotateFromRunProvenance:
    def test_cloned_agent_parent_id_is_original(self, tmp_path: Path) -> None:
        created = json.loads(forge_create("coder", "Writes code."))
        original_id = created["id"]

        plan_file = _make_plan(tmp_path, [_step("s1", "coder")])
        log_file = _make_run_log(tmp_path, plan_file, [_outcome("s1", "completed")])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert cloned.parent_id == original_id

    def test_multiple_failures_all_included_in_notes(self, tmp_path: Path) -> None:
        forge_create("coder", "Writes code.")

        plan_file = _make_plan(tmp_path, [
            _step("s1", "coder"),
            _step("s2", "coder"),
            _step("s3", "coder"),
        ])
        log_file = _make_run_log(tmp_path, plan_file, [
            _outcome("s1", "failed", "network error"),
            _outcome("s2", "failed", "timeout"),
            _outcome("s3", "completed"),
        ])

        result = json.loads(forge_annotate_from_run(str(log_file)))

        assert result["annotated"][0]["failure_delta"] == 2
        new_id = result["annotated"][0]["new_id"]
        assert state.registry_api is not None
        cloned = state.registry_api.get(new_id)
        assert cloned is not None
        assert "network error" in cloned.notes
        assert "timeout" in cloned.notes
        assert "s1" in cloned.notes
        assert "s2" in cloned.notes
