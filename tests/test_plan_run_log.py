"""Tests for swarm.plan.run_log."""

from __future__ import annotations

from pathlib import Path

from swarm.plan.run_log import (
    RunLog,
    StepOutcome,
    append_step_outcome,
    load_run_log,
    write_run_log,
)


class TestStepOutcome:
    def test_round_trip(self) -> None:
        o = StepOutcome(
            step_id="s1",
            status="completed",
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:01:00",
            message="ok",
        )
        assert StepOutcome.from_dict(o.to_dict()) == o

    def test_default_message(self) -> None:
        o = StepOutcome(
            step_id="s1", status="completed",
            started_at="t0", finished_at="t1",
        )
        assert o.message == ""


class TestRunLog:
    def test_round_trip(self) -> None:
        log = RunLog(
            plan_path="plan_v1.json",
            plan_version=1,
            started_at="t0",
            status="running",
            steps=[
                StepOutcome(step_id="s1", status="completed", started_at="t0", finished_at="t1"),
            ],
        )
        assert RunLog.from_dict(log.to_dict()).plan_path == "plan_v1.json"
        assert len(RunLog.from_dict(log.to_dict()).steps) == 1

    def test_completed_step_ids(self) -> None:
        log = RunLog(
            plan_path="p", plan_version=1, started_at="t0",
            steps=[
                StepOutcome(step_id="s1", status="completed", started_at="t0", finished_at="t1"),
                StepOutcome(step_id="s2", status="failed", started_at="t0", finished_at="t1"),
                StepOutcome(step_id="s3", status="completed", started_at="t0", finished_at="t1"),
            ],
        )
        assert log.completed_step_ids == {"s1", "s3"}

    def test_empty_steps(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        assert log.completed_step_ids == set()


class TestWriteLoadRunLog:
    def test_write_and_load(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p.json", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        loaded = load_run_log(path)
        assert loaded.plan_path == "p.json"
        assert loaded.plan_version == 1


class TestRunLogReplanCount:
    def test_default_replan_count(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        assert log.replan_count == 0

    def test_replan_count_round_trip(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0", replan_count=3)
        restored = RunLog.from_dict(log.to_dict())
        assert restored.replan_count == 3

    def test_replan_count_sparse_serialization_zero_omitted(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        d = log.to_dict()
        assert "replan_count" not in d

    def test_replan_count_sparse_serialization_nonzero_included(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0", replan_count=2)
        d = log.to_dict()
        assert d["replan_count"] == 2

    def test_from_dict_backward_compat_missing_defaults_to_zero(self) -> None:
        d = {"plan_path": "p", "plan_version": 1, "started_at": "t0"}
        log = RunLog.from_dict(d)
        assert log.replan_count == 0

    def test_replan_count_persists_through_write_load(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p.json", plan_version=1, started_at="t0", replan_count=5)
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        loaded = load_run_log(path)
        assert loaded.replan_count == 5


class TestStepOutcomeCostFields:
    def test_default_cost_fields_omitted_from_dict(self) -> None:
        o = StepOutcome(
            step_id="s1", status="completed",
            started_at="t0", finished_at="t1",
        )
        d = o.to_dict()
        assert "tokens_used" not in d
        assert "cost_usd" not in d
        assert "model" not in d

    def test_nonzero_cost_fields_included_in_dict(self) -> None:
        o = StepOutcome(
            step_id="s1", status="completed",
            started_at="t0", finished_at="t1",
            tokens_used=1500, cost_usd=0.003, model="claude-3",
        )
        d = o.to_dict()
        assert d["tokens_used"] == 1500
        assert d["cost_usd"] == 0.003
        assert d["model"] == "claude-3"

    def test_roundtrip_preserves_cost_fields(self) -> None:
        o = StepOutcome(
            step_id="s1", status="completed",
            started_at="t0", finished_at="t1",
            tokens_used=2000, cost_usd=0.05, model="claude-3-opus",
        )
        restored = StepOutcome.from_dict(o.to_dict())
        assert restored.tokens_used == 2000
        assert restored.cost_usd == 0.05
        assert restored.model == "claude-3-opus"
        assert restored == o

    def test_from_dict_without_cost_fields_defaults(self) -> None:
        d = {
            "step_id": "s1", "status": "completed",
            "started_at": "t0", "finished_at": "t1",
        }
        o = StepOutcome.from_dict(d)
        assert o.tokens_used == 0
        assert o.cost_usd == 0.0
        assert o.model == ""

    def test_cost_fields_persist_through_write_load(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="p.json", plan_version=1, started_at="t0",
            steps=[
                StepOutcome(
                    step_id="s1", status="completed",
                    started_at="t0", finished_at="t1",
                    tokens_used=500, cost_usd=0.01, model="claude-3",
                ),
            ],
        )
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        loaded = load_run_log(path)
        assert loaded.steps[0].tokens_used == 500
        assert loaded.steps[0].cost_usd == 0.01
        assert loaded.steps[0].model == "claude-3"


class TestAppendStepOutcome:
    def test_appends_and_persists(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p.json", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)

        outcome = StepOutcome(step_id="s1", status="completed", started_at="t0", finished_at="t1")
        updated = append_step_outcome(path, outcome)
        assert len(updated.steps) == 1

        reloaded = load_run_log(path)
        assert len(reloaded.steps) == 1
        assert reloaded.steps[0].step_id == "s1"
