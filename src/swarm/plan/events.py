"""Append-only event log for real-time plan execution progress."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PlanEvent:
    """A single execution event."""

    event_type: str  # step_started, step_completed, step_failed, step_skipped, run_started, run_completed, checkpoint_reached
    step_id: str = ""
    agent_type: str = ""
    message: str = ""
    timestamp: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_type": self.event_type,
            "timestamp": self.timestamp or datetime.now(tz=UTC).isoformat(),
        }
        if self.step_id:
            d["step_id"] = self.step_id
        if self.agent_type:
            d["agent_type"] = self.agent_type
        if self.message:
            d["message"] = self.message
        if self.data:
            d["data"] = self.data
        return d


class EventLog:
    """Append-only NDJSON event log for real-time progress tracking.

    Events are appended as newline-delimited JSON (one JSON object per line).
    Readers can tail the file for real-time updates.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, event: PlanEvent) -> None:
        """Append an event to the log file."""
        line = json.dumps(event.to_dict()) + "\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    def read_all(self) -> list[dict[str, Any]]:
        """Read all events from the log."""
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def read_since(self, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Read events from a byte offset. Returns (events, new_offset).

        This enables efficient polling: the caller passes the offset from
        the previous call to only get new events.
        """
        if not self._path.exists():
            return [], 0
        events: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            new_offset = f.tell()
        return events, new_offset
