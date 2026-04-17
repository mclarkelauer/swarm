"""Tests for swarm.plan.run_log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.errors import RunLogCorruptError
from swarm.plan.events import EventLog, PlanEvent
from swarm.plan.run_log import (
    BackgroundStepRecord,
    RunLog,
    StepOutcome,
    _backup_path,
    append_step_outcome,
    load_run_log,
    load_run_log_resilient,
    reconstruct_run_log_from_events,
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


# ---------------------------------------------------------------------------
# BackgroundStepRecord
# ---------------------------------------------------------------------------


class TestBackgroundStepRecord:
    def test_round_trip_basic(self) -> None:
        record = BackgroundStepRecord(
            step_id="s1",
            pid=12345,
            started_at="2026-04-17T12:00:00+00:00",
        )
        restored = BackgroundStepRecord.from_dict(record.to_dict())
        assert restored == record

    def test_round_trip_with_branch_index(self) -> None:
        record = BackgroundStepRecord(
            step_id="fan::2",
            pid=999,
            started_at="t0",
            branch_index=2,
        )
        restored = BackgroundStepRecord.from_dict(record.to_dict())
        assert restored == record
        assert restored.branch_index == 2

    def test_branch_index_omitted_when_none(self) -> None:
        record = BackgroundStepRecord(step_id="s1", pid=10, started_at="t0")
        d = record.to_dict()
        assert "branch_index" not in d

    def test_branch_index_emitted_when_set(self) -> None:
        record = BackgroundStepRecord(
            step_id="fan::0", pid=10, started_at="t0", branch_index=0,
        )
        d = record.to_dict()
        assert d["branch_index"] == 0


class TestRunLogBackgroundSteps:
    def test_default_empty_list(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        assert log.background_steps == []

    def test_background_steps_omitted_from_dict_when_empty(self) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        d = log.to_dict()
        assert "background_steps" not in d

    def test_background_steps_serialized_when_present(self) -> None:
        log = RunLog(
            plan_path="p", plan_version=1, started_at="t0",
            background_steps=[
                BackgroundStepRecord(step_id="s1", pid=42, started_at="t0"),
                BackgroundStepRecord(
                    step_id="fan::1", pid=43, started_at="t0", branch_index=1,
                ),
            ],
        )
        d = log.to_dict()
        assert len(d["background_steps"]) == 2
        assert d["background_steps"][0]["pid"] == 42
        assert d["background_steps"][1]["branch_index"] == 1

    def test_round_trip_preserves_background_steps(self, tmp_path: Path) -> None:
        log = RunLog(
            plan_path="p", plan_version=1, started_at="t0",
            background_steps=[
                BackgroundStepRecord(step_id="s1", pid=42, started_at="t0"),
            ],
        )
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        loaded = load_run_log(path)
        assert len(loaded.background_steps) == 1
        assert loaded.background_steps[0].pid == 42
        assert loaded.background_steps[0].step_id == "s1"

    def test_from_dict_backward_compat_missing_field(self) -> None:
        d = {"plan_path": "p", "plan_version": 1, "started_at": "t0"}
        log = RunLog.from_dict(d)
        assert log.background_steps == []


# ---------------------------------------------------------------------------
# .prev rolling backup
# ---------------------------------------------------------------------------


class TestPrevBackup:
    def test_first_write_creates_no_backup(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        assert path.exists()
        assert not _backup_path(path).exists()

    def test_second_write_creates_prev_backup(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        # Mutate and write again
        log.steps.append(
            StepOutcome(
                step_id="s1", status="completed",
                started_at="t0", finished_at="t1",
            )
        )
        write_run_log(log, path)
        backup = _backup_path(path)
        assert backup.exists()
        # Backup should hold the original (no steps); primary holds new.
        backup_data = json.loads(backup.read_text())
        primary_data = json.loads(path.read_text())
        assert backup_data["steps"] == []
        assert len(primary_data["steps"]) == 1

    def test_prev_backup_path_naming(self, tmp_path: Path) -> None:
        path = tmp_path / "run_log.json"
        assert _backup_path(path).name == "run_log.json.prev"


# ---------------------------------------------------------------------------
# Reconstruction from events.ndjson
# ---------------------------------------------------------------------------


class TestReconstructFromEvents:
    def _emit_events(self, path: Path, events: list[PlanEvent]) -> None:
        log = EventLog(path)
        for ev in events:
            log.emit(ev)

    def test_raises_when_events_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(RunLogCorruptError):
            reconstruct_run_log_from_events(tmp_path / "nope.ndjson")

    def test_raises_when_events_file_empty(self, tmp_path: Path) -> None:
        ev_path = tmp_path / "events.ndjson"
        ev_path.write_text("")
        with pytest.raises(RunLogCorruptError):
            reconstruct_run_log_from_events(ev_path)

    def test_rebuilds_completed_failed_skipped(self, tmp_path: Path) -> None:
        ev_path = tmp_path / "events.ndjson"
        self._emit_events(ev_path, [
            PlanEvent(event_type="run_started", message="goal"),
            PlanEvent(event_type="step_started", step_id="s1"),
            PlanEvent(event_type="step_completed", step_id="s1"),
            PlanEvent(event_type="step_started", step_id="s2"),
            PlanEvent(event_type="step_failed", step_id="s2", message="boom"),
            PlanEvent(event_type="step_skipped", step_id="s3"),
        ])

        rebuilt = reconstruct_run_log_from_events(ev_path)
        statuses = {o.step_id: o.status for o in rebuilt.steps}
        assert statuses == {
            "s1": "completed",
            "s2": "failed",
            "s3": "skipped",
        }
        assert rebuilt.completed_step_ids == {"s1"}

    def test_keeps_only_latest_outcome_per_step(self, tmp_path: Path) -> None:
        # A step that failed once then completed on retry should end up
        # marked completed in the reconstructed log.
        ev_path = tmp_path / "events.ndjson"
        self._emit_events(ev_path, [
            PlanEvent(event_type="run_started"),
            PlanEvent(event_type="step_failed", step_id="s1", message="try1"),
            PlanEvent(event_type="step_completed", step_id="s1"),
        ])
        rebuilt = reconstruct_run_log_from_events(ev_path)
        assert len(rebuilt.steps) == 1
        assert rebuilt.steps[0].status == "completed"

    def test_picks_up_checkpoint_id(self, tmp_path: Path) -> None:
        ev_path = tmp_path / "events.ndjson"
        self._emit_events(ev_path, [
            PlanEvent(event_type="run_started"),
            PlanEvent(event_type="step_completed", step_id="s1"),
            PlanEvent(event_type="checkpoint_reached", step_id="cp"),
        ])
        rebuilt = reconstruct_run_log_from_events(ev_path)
        assert rebuilt.checkpoint_step_id == "cp"

    def test_ignores_malformed_lines(self, tmp_path: Path) -> None:
        ev_path = tmp_path / "events.ndjson"
        ev_path.write_text(
            json.dumps({"event_type": "step_completed", "step_id": "s1"})
            + "\n{ this is not json }\n"
            + json.dumps({"event_type": "step_completed", "step_id": "s2"})
            + "\n"
        )
        rebuilt = reconstruct_run_log_from_events(ev_path)
        assert rebuilt.completed_step_ids == {"s1", "s2"}

    def test_explicit_plan_metadata_used_when_no_run_started(
        self, tmp_path: Path,
    ) -> None:
        ev_path = tmp_path / "events.ndjson"
        self._emit_events(ev_path, [
            PlanEvent(event_type="step_completed", step_id="s1"),
        ])
        rebuilt = reconstruct_run_log_from_events(
            ev_path, plan_path="custom.json", plan_version=7,
        )
        assert rebuilt.plan_path == "custom.json"
        assert rebuilt.plan_version == 7


# ---------------------------------------------------------------------------
# load_run_log_resilient: corruption recovery chain
# ---------------------------------------------------------------------------


class TestLoadRunLogResilient:
    def test_clean_load(self, tmp_path: Path) -> None:
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        loaded = load_run_log_resilient(path)
        assert loaded.plan_path == "p"

    def test_falls_back_to_prev_backup(self, tmp_path: Path) -> None:
        # Write two versions so a .prev backup exists, then corrupt the
        # primary file.
        log = RunLog(plan_path="p", plan_version=1, started_at="t0")
        path = tmp_path / "run_log.json"
        write_run_log(log, path)
        log.steps.append(StepOutcome(
            step_id="s1", status="completed",
            started_at="t0", finished_at="t1",
        ))
        write_run_log(log, path)

        # Corrupt the primary
        path.write_text("not valid json{")

        loaded = load_run_log_resilient(path)
        # The .prev backup held the original (no steps).
        assert loaded.plan_path == "p"
        assert loaded.steps == []

    def test_falls_back_to_events_when_no_backup(
        self, tmp_path: Path,
    ) -> None:
        path = tmp_path / "run_log.json"
        path.write_text("garbage")
        ev_path = tmp_path / "events.ndjson"
        EventLog(ev_path).emit(
            PlanEvent(event_type="step_completed", step_id="s1"),
        )

        loaded = load_run_log_resilient(path, events_path=ev_path)
        assert loaded.completed_step_ids == {"s1"}

    def test_default_events_path_is_sibling(self, tmp_path: Path) -> None:
        # When events_path is not passed, load_run_log_resilient should
        # look for events.ndjson alongside the run log.
        path = tmp_path / "run_log.json"
        path.write_text("garbage")
        EventLog(tmp_path / "events.ndjson").emit(
            PlanEvent(event_type="step_completed", step_id="s9"),
        )
        loaded = load_run_log_resilient(path)
        assert loaded.completed_step_ids == {"s9"}

    def test_raises_when_no_recovery_source(self, tmp_path: Path) -> None:
        path = tmp_path / "run_log.json"
        path.write_text("not json")
        with pytest.raises(RunLogCorruptError):
            load_run_log_resilient(path)

    def test_raises_when_file_missing_and_no_events(
        self, tmp_path: Path,
    ) -> None:
        path = tmp_path / "run_log.json"
        with pytest.raises(RunLogCorruptError):
            load_run_log_resilient(path)
