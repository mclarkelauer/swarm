"""HUD event emission for tmux status line integration.

Emits plan execution events that are consumed by the swarm-hud.py display script
to show real-time plan progress in tmux status bars.

State files are organized by tmux PID for multi-server isolation:
  ~/.swarm-tmux-hud/state/<tmux_pid>/plan_<run_id>.json

Events are emitted only when running inside tmux (TMUX_PANE is set).
All operations are atomic and race-free.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _get_state_dir() -> Path | None:
    """Get the HUD state directory for the current tmux session.

    Returns:
        Path to state directory, or None if not running in tmux.
    """
    if "TMUX_PANE" not in os.environ:
        return None

    # Get tmux PID for isolation
    try:
        result = subprocess.run(
            ["timeout", "1", "tmux", "display-message", "-p", "#{pid}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        tmux_pid = result.stdout.strip()
    except Exception:
        return None

    if not tmux_pid.isdigit():
        return None

    state_dir = Path.home() / ".swarm-tmux-hud" / "state" / tmux_pid
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _write_plan_state(run_id: str, updates: dict[str, Any]) -> None:
    """Atomically update plan state file.

    Args:
        run_id: Unique run identifier
        updates: Dictionary of fields to update (merged with existing state)
    """
    state_dir = _get_state_dir()
    if not state_dir:
        return  # Not in tmux, skip silently

    state_file = state_dir / f"plan_{run_id}.json"

    # Read existing state if present
    state: dict[str, Any] = {}
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception as e:
            logger.warning("hud.read_state_failed", error=str(e), file=str(state_file))

    # Merge updates
    state.update(updates)
    state["last_updated"] = datetime.now(UTC).isoformat()

    # Atomic write (tmp file + rename)
    tmp_file = state_file.with_suffix(f".tmp.{os.getpid()}")
    try:
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        tmp_file.replace(state_file)
    except Exception as e:
        logger.warning("hud.write_state_failed", error=str(e), file=str(state_file))
        tmp_file.unlink(missing_ok=True)


def emit_plan_start(
    run_id: str,
    plan_path: str,
    goal: str,
    total_steps: int,
    total_waves: int,
) -> None:
    """Emit plan start event.

    Args:
        run_id: Unique run identifier
        plan_path: Path to plan file
        goal: Plan goal description
        total_steps: Total number of steps in the plan
        total_waves: Total number of execution waves
    """
    logger.info(
        "hud.plan_start",
        run_id=run_id,
        goal=goal,
        total_steps=total_steps,
        total_waves=total_waves,
    )

    _write_plan_state(
        run_id,
        {
            "run_id": run_id,
            "plan_path": plan_path,
            "goal": goal,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "current_wave": 1,
            "total_waves": total_waves,
            "steps": {
                "total": total_steps,
                "completed": 0,
                "running": 0,
                "waiting": 0,
                "failed": 0,
            },
            "active_agents": [],
        },
    )


def emit_wave_start(run_id: str, wave_num: int) -> None:
    """Emit wave start event.

    Args:
        run_id: Unique run identifier
        wave_num: Wave number (1-indexed)
    """
    logger.info("hud.wave_start", run_id=run_id, wave_num=wave_num)
    _write_plan_state(run_id, {"current_wave": wave_num})


def emit_step_start(
    run_id: str,
    step_id: str,
    agent_type: str,
    session_id: str | None = None,
) -> None:
    """Emit step start event.

    Args:
        run_id: Unique run identifier
        step_id: Step identifier
        agent_type: Agent type name
        session_id: Optional Claude session ID for the agent
    """
    logger.info(
        "hud.step_start",
        run_id=run_id,
        step_id=step_id,
        agent_type=agent_type,
    )

    # Read current state to update active_agents list
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"
    if not state_file.exists():
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return

    # Add to active agents
    state["active_agents"].append(
        {
            "agent_type": agent_type,
            "session_id": session_id or "",
            "step_id": step_id,
            "status": "working",
            "started_at": datetime.now(UTC).isoformat(),
        }
    )

    # Update counts
    state["steps"]["running"] += 1

    _write_plan_state(run_id, state)


def emit_step_complete(run_id: str, step_id: str, success: bool) -> None:
    """Emit step complete event.

    Args:
        run_id: Unique run identifier
        step_id: Step identifier
        success: Whether the step completed successfully
    """
    logger.info(
        "hud.step_complete",
        run_id=run_id,
        step_id=step_id,
        success=success,
    )

    # Read current state to update active_agents list
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"
    if not state_file.exists():
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return

    # Remove from active agents
    state["active_agents"] = [a for a in state["active_agents"] if a["step_id"] != step_id]

    # Update counts
    state["steps"]["running"] -= 1
    if success:
        state["steps"]["completed"] += 1
    else:
        state["steps"]["failed"] += 1

    _write_plan_state(run_id, state)


def emit_step_waiting(run_id: str, step_id: str) -> None:
    """Emit step waiting event (agent waiting for user input).

    Args:
        run_id: Unique run identifier
        step_id: Step identifier
    """
    logger.info("hud.step_waiting", run_id=run_id, step_id=step_id)

    # Read current state to update agent status
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"
    if not state_file.exists():
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        return

    # Update agent status to waiting
    for agent in state["active_agents"]:
        if agent["step_id"] == step_id:
            agent["status"] = "waiting"
            agent["waiting_since"] = datetime.now(UTC).isoformat()

    # Update counts
    state["steps"]["waiting"] += 1

    _write_plan_state(run_id, state)


def emit_plan_complete(run_id: str, success: bool = True) -> None:
    """Emit plan complete event.

    Args:
        run_id: Unique run identifier
        success: Whether the plan completed successfully
    """
    logger.info("hud.plan_complete", run_id=run_id, success=success)

    status = "complete" if success else "failed"
    _write_plan_state(
        run_id,
        {
            "status": status,
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )


def cleanup_stale_state_files(max_age_hours: int = 24) -> None:
    """Clean up stale HUD state files.

    Args:
        max_age_hours: Maximum age in hours before a file is considered stale
    """
    state_root = Path.home() / ".swarm-tmux-hud" / "state"
    if not state_root.exists():
        return

    now = datetime.now().timestamp()
    max_age_seconds = max_age_hours * 3600

    for pid_dir in state_root.iterdir():
        if not pid_dir.is_dir():
            continue

        # Remove stale state files
        for state_file in pid_dir.glob("plan_*.json"):
            age = now - state_file.stat().st_mtime
            if age > max_age_seconds:
                state_file.unlink()
                logger.info("hud.cleanup_stale_file", file=str(state_file), age_hours=age / 3600)

        # Remove empty PID directories
        if not any(pid_dir.iterdir()):
            pid_dir.rmdir()
            logger.info("hud.cleanup_empty_dir", dir=str(pid_dir))
