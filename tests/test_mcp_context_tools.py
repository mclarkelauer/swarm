"""Tests for swarm.mcp.context_tools: context_set, context_get, context_get_all, context_delete."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.context.api import SharedContextAPI
from swarm.mcp import state
from swarm.mcp.context_tools import (
    context_delete,
    context_get,
    context_get_all,
    context_set,
)


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.context_api = SharedContextAPI(tmp_path / "context.db")


class TestContextSet:
    def test_context_set_returns_entry(self) -> None:
        result = json.loads(context_set("run-1", "api_schema", '{"v": 1}', set_by="agent-a"))
        assert result["run_id"] == "run-1"
        assert result["key"] == "api_schema"
        assert result["value"] == '{"v": 1}'
        assert result["set_by"] == "agent-a"
        assert "set_at" in result

    def test_context_set_default_set_by(self) -> None:
        result = json.loads(context_set("run-1", "k", "v"))
        assert result["set_by"] == ""


class TestContextGet:
    def test_context_set_and_get(self) -> None:
        context_set("run-1", "findings", "important data", set_by="researcher")
        result = json.loads(context_get("run-1", "findings"))
        assert result["key"] == "findings"
        assert result["value"] == "important data"

    def test_context_get_nonexistent(self) -> None:
        result = json.loads(context_get("run-1", "nonexistent"))
        assert result["key"] == "nonexistent"
        assert result["value"] is None


class TestContextGetAll:
    def test_context_get_all(self) -> None:
        context_set("run-1", "a", "1")
        context_set("run-1", "b", "2")
        context_set("run-1", "c", "3")
        result = json.loads(context_get_all("run-1"))
        assert result == {"a": "1", "b": "2", "c": "3"}

    def test_context_get_all_empty(self) -> None:
        result = json.loads(context_get_all("run-empty"))
        assert result == {}


class TestContextDelete:
    def test_context_delete(self) -> None:
        context_set("run-1", "temp", "data")
        result = json.loads(context_delete("run-1", "temp"))
        assert result["ok"] is True
        assert result["key"] == "temp"
        # Verify it's gone
        get_result = json.loads(context_get("run-1", "temp"))
        assert get_result["value"] is None

    def test_context_delete_nonexistent(self) -> None:
        result = json.loads(context_delete("run-1", "nope"))
        assert result["ok"] is False
        assert result["key"] == "nope"
