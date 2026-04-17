"""Tests for swarm.plan.events: PlanEvent, EventLog."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.plan.events import EventLog, PlanEvent

# ---------------------------------------------------------------------------
# PlanEvent serialization
# ---------------------------------------------------------------------------


class TestPlanEventSerialization:
    def test_event_serialization_minimal(self) -> None:
        """PlanEvent.to_dict() uses sparse serialization — only non-default fields."""
        event = PlanEvent(event_type="run_started", timestamp="2025-01-01T00:00:00+00:00")
        d = event.to_dict()
        assert d["event_type"] == "run_started"
        assert d["timestamp"] == "2025-01-01T00:00:00+00:00"
        assert "step_id" not in d
        assert "agent_type" not in d
        assert "message" not in d
        assert "data" not in d

    def test_event_serialization_full(self) -> None:
        """All fields are included when set."""
        event = PlanEvent(
            event_type="step_completed",
            step_id="s1",
            agent_type="worker",
            message="done",
            timestamp="2025-01-01T00:00:00+00:00",
            data={"exit_code": 0},
        )
        d = event.to_dict()
        assert d["event_type"] == "step_completed"
        assert d["step_id"] == "s1"
        assert d["agent_type"] == "worker"
        assert d["message"] == "done"
        assert d["data"] == {"exit_code": 0}

    def test_event_auto_timestamp(self) -> None:
        """When timestamp is empty, to_dict() fills in the current time."""
        event = PlanEvent(event_type="run_started")
        d = event.to_dict()
        assert "timestamp" in d
        assert d["timestamp"] != ""


# ---------------------------------------------------------------------------
# EventLog
# ---------------------------------------------------------------------------


class TestEventLogEmit:
    def test_emit_creates_file(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))

        assert log_path.exists()

    def test_emit_appends_ndjson(self, tmp_path: Path) -> None:
        """Each emit appends one JSON line."""
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))
        log.emit(PlanEvent(event_type="step_started", step_id="s1", timestamp="t1"))
        log.emit(PlanEvent(event_type="step_completed", step_id="s1", timestamp="t2"))

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

        # Each line is valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "event_type" in parsed

    def test_emit_creates_parent_dirs(self, tmp_path: Path) -> None:
        log_path = tmp_path / "sub" / "dir" / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))

        assert log_path.exists()


class TestEventLogReadAll:
    def test_read_all(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))
        log.emit(PlanEvent(event_type="step_completed", step_id="s1", timestamp="t1"))

        events = log.read_all()
        assert len(events) == 2
        assert events[0]["event_type"] == "run_started"
        assert events[1]["event_type"] == "step_completed"
        assert events[1]["step_id"] == "s1"

    def test_read_all_empty_file(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.ndjson"
        log_path.write_text("", encoding="utf-8")
        log = EventLog(log_path)

        events = log.read_all()
        assert events == []

    def test_read_all_nonexistent_file(self, tmp_path: Path) -> None:
        log_path = tmp_path / "nope.ndjson"
        log = EventLog(log_path)

        events = log.read_all()
        assert events == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed JSON lines are silently skipped."""
        log_path = tmp_path / "events.ndjson"
        log_path.write_text(
            '{"event_type": "run_started", "timestamp": "t0"}\n'
            'not valid json\n'
            '{"event_type": "step_completed", "timestamp": "t1"}\n',
            encoding="utf-8",
        )
        log = EventLog(log_path)

        events = log.read_all()
        assert len(events) == 2
        assert events[0]["event_type"] == "run_started"
        assert events[1]["event_type"] == "step_completed"


class TestEventLogReadSince:
    def test_read_since_offset(self, tmp_path: Path) -> None:
        """read_since returns only events after the byte offset."""
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))
        log.emit(PlanEvent(event_type="step_started", step_id="s1", timestamp="t1"))

        # Read all from beginning
        events_1, offset_1 = log.read_since(0)
        assert len(events_1) == 2
        assert offset_1 > 0

        # Emit another event
        log.emit(PlanEvent(event_type="step_completed", step_id="s1", timestamp="t2"))

        # Read only the new event
        events_2, offset_2 = log.read_since(offset_1)
        assert len(events_2) == 1
        assert events_2[0]["event_type"] == "step_completed"
        assert offset_2 > offset_1

    def test_read_since_empty(self, tmp_path: Path) -> None:
        """Reading from a nonexistent file returns ([], 0)."""
        log_path = tmp_path / "nope.ndjson"
        log = EventLog(log_path)

        events, offset = log.read_since(0)
        assert events == []
        assert offset == 0

    def test_read_since_no_new_events(self, tmp_path: Path) -> None:
        """Reading from the current end returns empty list."""
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)

        log.emit(PlanEvent(event_type="run_started", timestamp="t0"))

        _, offset = log.read_since(0)
        events, new_offset = log.read_since(offset)

        assert events == []
        assert new_offset == offset

    def test_read_since_malformed_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed lines are skipped during read_since."""
        log_path = tmp_path / "events.ndjson"
        log_path.write_text(
            '{"event_type": "a", "timestamp": "t0"}\n'
            'bad json\n'
            '{"event_type": "b", "timestamp": "t1"}\n',
            encoding="utf-8",
        )
        log = EventLog(log_path)

        events, offset = log.read_since(0)
        assert len(events) == 2
        assert events[0]["event_type"] == "a"
        assert events[1]["event_type"] == "b"


class TestEventLogPath:
    def test_path_property(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.ndjson"
        log = EventLog(log_path)
        assert log.path == log_path
