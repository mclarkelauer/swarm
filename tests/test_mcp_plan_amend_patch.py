"""Tests for plan_amend and plan_patch_step MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.plan_tools import plan_amend, plan_patch_step

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


def _linear_plan(tmp_path: Path) -> Path:
    """Save a simple three-step linear plan (s1 -> s2 -> s3) and return path."""
    data = {
        "version": 1,
        "goal": "linear goal",
        "steps": [
            {"id": "s1", "type": "task", "prompt": "step one", "agent_type": "worker"},
            {
                "id": "s2",
                "type": "task",
                "prompt": "step two",
                "agent_type": "worker",
                "depends_on": ["s1"],
            },
            {
                "id": "s3",
                "type": "task",
                "prompt": "step three",
                "agent_type": "worker",
                "depends_on": ["s2"],
            },
        ],
    }
    return _write_plan(tmp_path, data)


def _single_step_plan(tmp_path: Path) -> Path:
    """Save a plan with one step and return its path."""
    data = {
        "version": 1,
        "goal": "single step goal",
        "steps": [
            {"id": "only", "type": "task", "prompt": "do it", "agent_type": "worker"},
        ],
    }
    return _write_plan(tmp_path, data)


# ---------------------------------------------------------------------------
# plan_amend — happy path
# ---------------------------------------------------------------------------


class TestPlanAmendHappyPath:
    def test_returns_success_keys(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s1b", "type": "task", "prompt": "inserted", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))

        assert result["errors"] == []
        assert result["inserted_steps"] == ["s1b"]
        assert result["path"] is not None
        assert Path(result["path"]).exists()

    def test_version_incremented(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "extra", "type": "task", "prompt": "extra step", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        assert result["version"] == 2

    def test_new_step_appears_in_saved_plan(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s1b", "type": "task", "prompt": "in the middle", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_ids = [s["id"] for s in saved["steps"]]
        assert step_ids == ["s1", "s1b", "s2", "s3"]

    def test_order_when_inserting_after_middle_step(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s2b", "type": "task", "prompt": "between two and three", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s2", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_ids = [s["id"] for s in saved["steps"]]
        assert step_ids == ["s1", "s2", "s2b", "s3"]

    def test_inserting_multiple_new_steps(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "na", "type": "task", "prompt": "first new", "agent_type": "worker"},
            {"id": "nb", "type": "task", "prompt": "second new", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        assert result["errors"] == []
        assert result["inserted_steps"] == ["na", "nb"]
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_ids = [s["id"] for s in saved["steps"]]
        assert step_ids == ["s1", "na", "nb", "s2", "s3"]


# ---------------------------------------------------------------------------
# plan_amend — automatic dependency wiring
# ---------------------------------------------------------------------------


class TestPlanAmendDependencyWiring:
    def test_new_step_without_deps_gets_insert_after_as_dep(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s1b", "type": "task", "prompt": "auto-dep", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        s1b = next(s for s in saved["steps"] if s["id"] == "s1b")
        assert s1b["depends_on"] == ["s1"]

    def test_new_step_with_explicit_deps_keeps_them(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        # s1b explicitly depends on s1 — this should be preserved as-is
        new_steps = json.dumps([
            {
                "id": "s1b",
                "type": "task",
                "prompt": "explicit dep",
                "agent_type": "worker",
                "depends_on": ["s1"],
            },
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        s1b = next(s for s in saved["steps"] if s["id"] == "s1b")
        assert s1b["depends_on"] == ["s1"]

    def test_multiple_new_steps_chained_automatically(self, tmp_path: Path) -> None:
        """Each new step without explicit deps should depend on the previous new step."""
        path = _single_step_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "na", "type": "task", "prompt": "first", "agent_type": "worker"},
            {"id": "nb", "type": "task", "prompt": "second", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "only", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["na"]["depends_on"] == ["only"]
        assert step_map["nb"]["depends_on"] == ["na"]


# ---------------------------------------------------------------------------
# plan_amend — downstream rewiring
# ---------------------------------------------------------------------------


class TestPlanAmendRewiring:
    def test_downstream_step_rewired_to_last_new_step(self, tmp_path: Path) -> None:
        """s2 originally depends on s1; after inserting s1b after s1, s2 should depend on s1b."""
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s1b", "type": "task", "prompt": "new middle", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert "s1b" in step_map["s2"]["depends_on"]
        assert "s1" not in step_map["s2"]["depends_on"]

    def test_rewiring_uses_last_of_multiple_new_steps(self, tmp_path: Path) -> None:
        """When two steps are inserted, downstream should depend on the second (last) one."""
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "na", "type": "task", "prompt": "first", "agent_type": "worker"},
            {"id": "nb", "type": "task", "prompt": "second", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert "nb" in step_map["s2"]["depends_on"]
        assert "na" not in step_map["s2"]["depends_on"]
        assert "s1" not in step_map["s2"]["depends_on"]

    def test_step_not_depending_on_anchor_is_not_rewired(self, tmp_path: Path) -> None:
        """s1 does not depend on anything — it should remain unchanged."""
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "s1b", "type": "task", "prompt": "new", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s1"].get("depends_on", []) == []


# ---------------------------------------------------------------------------
# plan_amend — error cases
# ---------------------------------------------------------------------------


class TestPlanAmendErrors:
    def test_file_not_found(self, tmp_path: Path) -> None:
        result = json.loads(
            plan_amend(str(tmp_path / "missing.json"), "s1", "[]")
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_insert_after_unknown_step(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_amend(str(path), "nonexistent", json.dumps([
                {"id": "x", "type": "task", "prompt": "p", "agent_type": "w"},
            ]))
        )
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_id_conflict_returns_error(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        # s2 already exists in the plan
        new_steps = json.dumps([
            {"id": "s2", "type": "task", "prompt": "duplicate", "agent_type": "worker"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        assert "error" in result
        assert "s2" in result["error"]

    def test_invalid_new_steps_json(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(plan_amend(str(path), "s1", "{not valid json}"))
        assert "error" in result
        assert "Invalid new_steps_json" in result["error"]

    def test_cycle_in_amended_plan_returns_errors_no_save(self, tmp_path: Path) -> None:
        """If manually wired depends_on creates a cycle, errors are returned without saving."""
        path = _linear_plan(tmp_path)
        # s1b depends on s3 (which is downstream), creating a cycle: s3 -> s2 -> s1b -> s3
        new_steps = json.dumps([
            {
                "id": "s1b",
                "type": "task",
                "prompt": "cyclic",
                "agent_type": "worker",
                "depends_on": ["s3"],
            },
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        assert len(result["errors"]) > 0
        assert result["path"] is None
        # Only the original plan file should exist
        assert len(list(tmp_path.glob("plan_v*.json"))) == 1

    def test_validation_failure_does_not_save(self, tmp_path: Path) -> None:
        """A new step with an invalid type should fail validation without saving."""
        path = _linear_plan(tmp_path)
        new_steps = json.dumps([
            {"id": "bad", "type": "bogus_type", "prompt": "p", "agent_type": "w"},
        ])
        result = json.loads(plan_amend(str(path), "s1", new_steps))
        assert len(result["errors"]) > 0
        assert result["path"] is None
        assert len(list(tmp_path.glob("plan_v*.json"))) == 1


# ---------------------------------------------------------------------------
# plan_patch_step — happy path
# ---------------------------------------------------------------------------


class TestPlanPatchStepHappyPath:
    def test_returns_success_keys(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"prompt": "updated prompt"}))
        )
        assert result["errors"] == []
        assert result["patched_step"] == "s1"
        assert result["path"] is not None
        assert Path(result["path"]).exists()

    def test_version_incremented(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"prompt": "new"}))
        )
        assert result["version"] == 2

    def test_patch_prompt(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s2", json.dumps({"prompt": "patched step two"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s2"]["prompt"] == "patched step two"

    def test_patch_agent_type(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"agent_type": "specialist"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s1"]["agent_type"] == "specialist"

    def test_patch_spawn_mode(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s3", json.dumps({"spawn_mode": "background"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s3"]["spawn_mode"] == "background"

    def test_patch_depends_on(self, tmp_path: Path) -> None:
        """Patching depends_on of s3 from [s2] to [s1] should be accepted."""
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s3", json.dumps({"depends_on": ["s1"]}))
        )
        assert result["errors"] == []
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s3"]["depends_on"] == ["s1"]

    def test_unpatched_steps_unchanged(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"prompt": "changed"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        # s2 and s3 must be untouched
        assert step_map["s2"]["prompt"] == "step two"
        assert step_map["s3"]["prompt"] == "step three"

    def test_patch_output_artifact(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s2", json.dumps({"output_artifact": "report.md"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s2"]["output_artifact"] == "report.md"

    def test_patch_on_failure(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"on_failure": "skip"}))
        )
        saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        step_map = {s["id"]: s for s in saved["steps"]}
        assert step_map["s1"]["on_failure"] == "skip"


# ---------------------------------------------------------------------------
# plan_patch_step — error cases
# ---------------------------------------------------------------------------


class TestPlanPatchStepErrors:
    def test_file_not_found(self, tmp_path: Path) -> None:
        result = json.loads(
            plan_patch_step(str(tmp_path / "nope.json"), "s1", "{}")
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_step_not_found(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "ghost", json.dumps({"prompt": "x"}))
        )
        assert "error" in result
        assert "ghost" in result["error"]

    def test_invalid_overrides_json(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(plan_patch_step(str(path), "s1", "not json at all"))
        assert "error" in result
        assert "Invalid overrides_json" in result["error"]

    def test_invalid_patch_causes_validation_error_no_save(self, tmp_path: Path) -> None:
        """Patching type to an invalid value should produce validation errors."""
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"type": "invalid_type"}))
        )
        assert len(result["errors"]) > 0
        assert result["path"] is None
        # Only original plan_v1.json should be on disk
        assert len(list(tmp_path.glob("plan_v*.json"))) == 1

    def test_patch_introduces_cycle_returns_errors(self, tmp_path: Path) -> None:
        """Patching s1 to depend on s3 creates a cycle."""
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"depends_on": ["s3"]}))
        )
        assert len(result["errors"]) > 0
        assert result["path"] is None

    def test_patched_step_echoed_in_error_response(self, tmp_path: Path) -> None:
        """Even on validation failure, patched_step should be in the response."""
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"type": "bad"}))
        )
        assert result["patched_step"] == "s1"

    def test_depends_on_unknown_step_fails_validation(self, tmp_path: Path) -> None:
        path = _linear_plan(tmp_path)
        result = json.loads(
            plan_patch_step(str(path), "s1", json.dumps({"depends_on": ["nonexistent"]}))
        )
        assert len(result["errors"]) > 0
        assert result["path"] is None
