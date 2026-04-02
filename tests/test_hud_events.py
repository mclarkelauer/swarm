"""Tests for HUD event emission."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.hud.events import (
    cleanup_stale_state_files,
    emit_plan_complete,
    emit_plan_start,
    emit_step_complete,
    emit_step_start,
)


@pytest.fixture
def mock_tmux_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mock tmux environment variables and state directory."""
    monkeypatch.setenv("TMUX_PANE", "%0")

    # Create state directory in tmp_path structure
    hud_dir = tmp_path / ".swarm-tmux-hud"
    state_dir = hud_dir / "state" / "12345"
    state_dir.mkdir(parents=True)

    # Mock subprocess call to return tmux PID
    def mock_run(*args, **kwargs):
        class Result:
            stdout = "12345"
            returncode = 0

        return Result()

    monkeypatch.setattr("swarm.hud.events.subprocess.run", mock_run)
    monkeypatch.setattr("swarm.hud.events.Path.home", lambda: tmp_path)

    return state_dir


def test_emit_plan_start(mock_tmux_env: Path):
    """Test plan start event emission."""
    emit_plan_start(
        run_id="test-run-1",
        plan_path="/path/to/plan.json",
        goal="Build test feature",
        total_steps=5,
        total_waves=2,
    )

    state_file = mock_tmux_env / "plan_test-run-1.json"
    assert state_file.exists()

    with open(state_file) as f:
        state = json.load(f)

    assert state["run_id"] == "test-run-1"
    assert state["plan_path"] == "/path/to/plan.json"
    assert state["goal"] == "Build test feature"
    assert state["status"] == "running"
    assert state["current_wave"] == 1
    assert state["total_waves"] == 2
    assert state["steps"]["total"] == 5
    assert state["steps"]["completed"] == 0
    assert state["active_agents"] == []


def test_emit_step_start(mock_tmux_env: Path):
    """Test step start event emission."""
    # First create a plan
    emit_plan_start(
        run_id="test-run-2",
        plan_path="/path/to/plan.json",
        goal="Test",
        total_steps=3,
        total_waves=1,
    )

    # Emit step start
    emit_step_start(
        run_id="test-run-2",
        step_id="step1",
        agent_type="test-agent",
        session_id="session-123",
    )

    state_file = mock_tmux_env / "plan_test-run-2.json"
    with open(state_file) as f:
        state = json.load(f)

    assert len(state["active_agents"]) == 1
    agent = state["active_agents"][0]
    assert agent["step_id"] == "step1"
    assert agent["agent_type"] == "test-agent"
    assert agent["session_id"] == "session-123"
    assert agent["status"] == "working"
    assert state["steps"]["running"] == 1


def test_emit_step_complete_success(mock_tmux_env: Path):
    """Test step complete event (success)."""
    emit_plan_start("test-run-3", "/plan.json", "Test", 3, 1)
    emit_step_start("test-run-3", "step1", "agent1", None)

    emit_step_complete("test-run-3", "step1", success=True)

    state_file = mock_tmux_env / "plan_test-run-3.json"
    with open(state_file) as f:
        state = json.load(f)

    assert len(state["active_agents"]) == 0
    assert state["steps"]["running"] == 0
    assert state["steps"]["completed"] == 1
    assert state["steps"]["failed"] == 0


def test_emit_step_complete_failure(mock_tmux_env: Path):
    """Test step complete event (failure)."""
    emit_plan_start("test-run-4", "/plan.json", "Test", 3, 1)
    emit_step_start("test-run-4", "step1", "agent1", None)

    emit_step_complete("test-run-4", "step1", success=False)

    state_file = mock_tmux_env / "plan_test-run-4.json"
    with open(state_file) as f:
        state = json.load(f)

    assert len(state["active_agents"]) == 0
    assert state["steps"]["running"] == 0
    assert state["steps"]["completed"] == 0
    assert state["steps"]["failed"] == 1


def test_emit_plan_complete(mock_tmux_env: Path):
    """Test plan complete event emission."""
    emit_plan_start("test-run-5", "/plan.json", "Test", 1, 1)

    emit_plan_complete("test-run-5", success=True)

    state_file = mock_tmux_env / "plan_test-run-5.json"
    with open(state_file) as f:
        state = json.load(f)

    assert state["status"] == "complete"
    assert "completed_at" in state


def test_multiple_active_agents(mock_tmux_env: Path):
    """Test multiple agents running in parallel."""
    emit_plan_start("test-run-6", "/plan.json", "Test", 5, 2)

    # Start 3 agents
    emit_step_start("test-run-6", "step1", "agent-a", "session-1")
    emit_step_start("test-run-6", "step2", "agent-b", "session-2")
    emit_step_start("test-run-6", "step3", "agent-c", "session-3")

    state_file = mock_tmux_env / "plan_test-run-6.json"
    with open(state_file) as f:
        state = json.load(f)

    assert len(state["active_agents"]) == 3
    assert state["steps"]["running"] == 3

    # Complete one
    emit_step_complete("test-run-6", "step1", success=True)

    with open(state_file) as f:
        state = json.load(f)

    assert len(state["active_agents"]) == 2
    assert state["steps"]["running"] == 2
    assert state["steps"]["completed"] == 1


def test_no_tmux_silent_fail(monkeypatch: pytest.MonkeyPatch):
    """Test that events are silent when not in tmux."""
    monkeypatch.delenv("TMUX_PANE", raising=False)

    # Should not raise
    emit_plan_start("test", "/plan.json", "Test", 1, 1)
    emit_step_start("test", "step1", "agent", None)
    emit_step_complete("test", "step1", True)
    emit_plan_complete("test", True)


def test_cleanup_stale_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test cleanup of old state files."""
    monkeypatch.setattr("swarm.hud.events.Path.home", lambda: tmp_path)

    state_dir = tmp_path / ".swarm-tmux-hud" / "state" / "12345"
    state_dir.mkdir(parents=True)

    # Create some state files
    (state_dir / "plan_old.json").write_text("{}")
    (state_dir / "plan_recent.json").write_text("{}")

    # Make one file old
    old_file = state_dir / "plan_old.json"
    old_mtime = old_file.stat().st_mtime - (25 * 3600)  # 25 hours ago
    os.utime(old_file, (old_mtime, old_mtime))

    # Cleanup with 24 hour threshold
    cleanup_stale_state_files(max_age_hours=24)

    # Old file should be gone, recent should remain
    assert not old_file.exists()
    assert (state_dir / "plan_recent.json").exists()


def test_atomic_writes_on_concurrent_updates(mock_tmux_env: Path):
    """Test that concurrent updates don't corrupt state."""
    # This is a basic test - real atomic behavior is system-level
    emit_plan_start("test-run-7", "/plan.json", "Test", 10, 3)

    # Rapid updates
    for i in range(5):
        emit_step_start("test-run-7", f"step{i}", f"agent{i}", None)

    state_file = mock_tmux_env / "plan_test-run-7.json"
    with open(state_file) as f:
        state = json.load(f)

    # All updates should be present
    assert len(state["active_agents"]) == 5
    assert state["steps"]["running"] == 5


def test_state_persistence_across_emits(mock_tmux_env: Path):
    """Test that state is correctly merged across multiple emits."""
    emit_plan_start("test-run-8", "/plan.json", "Test", 3, 1)

    state_file = mock_tmux_env / "plan_test-run-8.json"

    # Check initial state
    with open(state_file) as f:
        state1 = json.load(f)
    assert state1["status"] == "running"

    # Add a step
    emit_step_start("test-run-8", "step1", "agent1", None)

    with open(state_file) as f:
        state2 = json.load(f)

    # Original fields should still be there
    assert state2["run_id"] == state1["run_id"]
    assert state2["plan_path"] == state1["plan_path"]
    assert state2["goal"] == state1["goal"]
    # Plus new agent
    assert len(state2["active_agents"]) == 1
