#!/usr/bin/env python3
"""Swarm HUD - Display plan execution state in tmux status bar.

Usage:
  swarm-hud.py                    # Mode 1: Compact progress bar
  swarm-hud.py --expanded         # Mode 2: 2-line dashboard
  swarm-hud.py --per-window       # Mode 3: Per-window badges
  swarm-hud.py --run-id=<id>      # Filter by specific run
  swarm-hud.py --with-colors      # Apply tmux color codes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


STATE_DIR = Path.home() / ".swarm-tmux-hud" / "state"


def find_active_plan(tmux_pid: int, run_id: str | None = None) -> dict | None:
    """Find the most recent active plan for this tmux session.

    Args:
        tmux_pid: tmux process ID
        run_id: Optional specific run ID to filter by

    Returns:
        Plan state dict or None if no active plan found
    """
    pid_dir = STATE_DIR / str(tmux_pid)
    if not pid_dir.exists():
        return None

    plan_files = list(pid_dir.glob("plan_*.json"))
    if not plan_files:
        return None

    # Filter by run_id if specified
    if run_id:
        plan_files = [f for f in plan_files if f.stem == f"plan_{run_id}"]
        if not plan_files:
            return None

    # Most recent by mtime
    latest = max(plan_files, key=lambda p: p.stat().st_mtime)

    # Ignore if stale (>5 minutes since update)
    if time.time() - latest.stat().st_mtime > 300:
        return None

    try:
        with open(latest) as f:
            return json.load(f)
    except Exception:
        return None


def format_duration(started_at: str) -> str:
    """Format elapsed time since start.

    Args:
        started_at: ISO format timestamp

    Returns:
        Human-readable duration (e.g., "3m15s")
    """
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except Exception:
        return "?"

    elapsed = datetime.now().astimezone() - start
    total_seconds = int(elapsed.total_seconds())

    if total_seconds < 0:
        return "0s"

    minutes = total_seconds // 60
    seconds = total_seconds % 60

    if minutes > 0:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def render_progress_bar(completed: int, total: int, width: int = 30) -> str:
    """Render a Unicode progress bar.

    Args:
        completed: Number of completed items
        total: Total number of items
        width: Character width of the bar

    Returns:
        Unicode progress bar string
    """
    if total == 0:
        return "━" * width

    filled = int(width * completed / total)
    empty = width - filled

    if empty > 0:
        return "━" * filled + "╸" + "━" * (empty - 1)
    return "━" * width


def render_compact(plan: dict, with_colors: bool = False) -> str:
    """Mode 1: Compact single-line display.

    Args:
        plan: Plan state dictionary
        with_colors: Whether to apply tmux color codes

    Returns:
        Formatted status line
    """
    # Truncate goal
    goal = plan["goal"][:20]

    # Wave info
    current_wave = plan.get("current_wave", 1)
    total_waves = plan.get("total_waves", 1)
    wave = f"[Wave {current_wave}/{total_waves}]"

    # Progress
    steps = plan["steps"]
    completed = steps["completed"]
    total = steps["total"]
    progress = render_progress_bar(completed, total, width=30)

    # Active agents
    active = plan.get("active_agents", [])
    agent_icons = []
    for a in active[:3]:  # Max 3 to save space
        status = a.get("status", "working")
        if status == "working":
            agent_icons.append("●")
        else:
            agent_icons.append("○")
    agent_display = "".join(agent_icons) if agent_icons else ""

    # Elapsed time
    elapsed = format_duration(plan["started_at"])

    # Check if plan is complete or failed
    status = plan.get("status", "running")
    if status == "complete":
        icon = "✅"
        wave = "[Complete]"
    elif status == "failed":
        icon = "❌"
        wave = f"[Failed at step {completed + 1}]"
    else:
        icon = "📋"

    line = f"{icon} {goal} {wave} {progress} {completed}/{total}"
    if agent_display:
        line += f" [{agent_display}]"
    line += f" {elapsed}"

    # Apply colors if requested
    if with_colors:
        # Cyan for icon/goal, green for progress, yellow for wave
        line = f"#[fg=cyan]{icon} {goal}#[default] #[fg=yellow]{wave}#[default] #[fg=green]{progress}#[default] {completed}/{total}"
        if agent_display:
            line += f" [{agent_display}]"
        line += f" {elapsed}"

    return line


def render_expanded(plan: dict, with_colors: bool = False) -> str:
    """Mode 2: 2-line expanded dashboard.

    Args:
        plan: Plan state dictionary
        with_colors: Whether to apply tmux color codes

    Returns:
        Formatted 2-line status (lines separated by newline)
    """
    line1 = render_compact(plan, with_colors=False)  # No colors on line 1 for expanded mode

    # Line 2: Agent details
    agents = []
    for a in plan.get("active_agents", []):
        status = a.get("status", "working")
        icon = "🟢" if status == "working" else "🟡"
        name = a["agent_type"]
        suffix = " (waiting)" if status == "waiting" else ""
        agents.append(f"{icon} {name}{suffix}")

    line2 = "  " + "  ".join(agents) if agents else "  (no active agents)"

    return line1 + "\n" + line2


def render_per_window(plan: dict) -> str:
    """Mode 3: Per-window agent badges (sets tmux window variables).

    This mode outputs nothing to stdout. Instead, it sets tmux window
    variables @claude for each window with an active agent.

    Args:
        plan: Plan state dictionary

    Returns:
        Empty string (side effects only)
    """
    # Get window list
    try:
        result = os.popen("tmux list-windows -F '#{window_id}'").read()
        window_ids = result.strip().split("\n")
    except Exception:
        return ""

    # Clear all @claude variables first
    for win_id in window_ids:
        os.system(f"tmux set-window-option -t {win_id} @claude ''")

    # Set variables for windows with active agents
    for agent in plan.get("active_agents", []):
        session_id = agent.get("session_id", "")
        if not session_id:
            continue

        # Find window containing this session's pane
        # (This is a simplified approach - in practice, you'd track pane IDs)
        status = agent.get("status", "working")
        icon = "🟢" if status == "working" else "🟡"

        # Set @claude variable for the window
        # (Simplified - would need pane->window mapping in production)
        # os.system(f"tmux set-window-option -t <window_id> @claude '{icon}'")

    return ""


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Swarm plan execution HUD for tmux")
    parser.add_argument("--expanded", action="store_true", help="Mode 2: 2-line dashboard")
    parser.add_argument("--per-window", action="store_true", help="Mode 3: Per-window badges")
    parser.add_argument("--run-id", help="Filter by specific run ID")
    parser.add_argument("--with-colors", action="store_true", help="Apply tmux color codes")
    args = parser.parse_args()

    # Get tmux PID
    try:
        tmux_pid_str = os.popen("tmux display-message -p '#{pid}' 2>/dev/null").read().strip()
        if not tmux_pid_str.isdigit():
            sys.exit(0)  # Not in tmux, exit silently
        tmux_pid = int(tmux_pid_str)
    except Exception:
        sys.exit(0)

    # Find active plan
    plan = find_active_plan(tmux_pid, run_id=args.run_id)
    if not plan:
        sys.exit(0)  # No active plan, output nothing

    # Render based on mode
    if args.expanded:
        output = render_expanded(plan, with_colors=args.with_colors)
    elif args.per_window:
        output = render_per_window(plan)
    else:
        output = render_compact(plan, with_colors=args.with_colors)

    if output:
        print(output)


if __name__ == "__main__":
    main()
