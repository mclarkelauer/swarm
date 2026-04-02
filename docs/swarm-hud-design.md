# Swarm HUD Design

Adaptation of tmux-statusline for multi-agent plan orchestration.

## Problem Statement

Unlike single-agent Claude Code sessions, Swarm orchestrates multiple agents executing a DAG-based plan. The tmux-statusline "working/waiting/idle" model doesn't capture:

1. **Plan-level progress** - How many steps complete out of total?
2. **Parallel execution** - Which agents are running simultaneously?
3. **DAG state** - Which steps are blocked vs ready vs running?
4. **Wave execution** - Which execution wave are we in?
5. **Multi-agent coordination** - Agent A waiting on Agent B's output

## Design Philosophy

**"See the orchestra, not just the conductor"**

The HUD should show the **execution state of the plan**, not just the orchestrator's state.

## Proposed Display Modes

### Mode 1: Plan Progress Bar (Default)

Compact single-line display showing overall plan state:

```
📋 api-security [Wave 2/4] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6/12 [●●○] 3m15s
```

Components:
- `📋 api-security` - Plan goal (truncated)
- `[Wave 2/4]` - Current/total execution waves
- `━━━━━━━` - Progress bar (filled/empty)
- `6/12` - Steps complete/total
- `[●●○]` - Active agents: ● running, ○ waiting for input
- `3m15s` - Elapsed time since plan started

### Mode 2: Expanded Dashboard (2-line)

More detail for complex plans:

```
📋 api-security | Wave 2/4 | 6/12 steps | ⏱ 3m15s
  🟢 implementer  🟢 test-writer  🟡 code-reviewer (waiting)
```

Line 1: Plan metadata
Line 2: Active agents with states

### Mode 3: Per-Window Agent Badges

Integrate with tmux window names to show which agent is in which window:

```
1:orchestrator 📋  2:implementer 🟢  3:test-writer 🟢  4:code-reviewer 🟡
```

## State File Structure

Extend the tmux-statusline pattern with plan-specific state:

```
~/.swarm-tmux-hud/state/<tmux_pid>/
  plan_<run_id>.json          # Plan execution state
  agent_<session_id>.json     # Individual agent states (reuse tmux-statusline format)
```

### plan_<run_id>.json

```json
{
  "run_id": "abc123",
  "plan_path": "/path/to/plan_v1.json",
  "goal": "Build and validate API security",
  "status": "running",
  "started_at": "2026-04-02T13:00:00Z",
  "current_wave": 2,
  "total_waves": 4,
  "steps": {
    "total": 12,
    "completed": 6,
    "running": 2,
    "waiting": 1,
    "blocked": 3
  },
  "active_agents": [
    {
      "agent_type": "implementer",
      "session_id": "session-123",
      "step_id": "implement",
      "status": "working",
      "started_at": "2026-04-02T13:02:00Z"
    },
    {
      "agent_type": "test-writer",
      "session_id": "session-456",
      "step_id": "test",
      "status": "working",
      "started_at": "2026-04-02T13:02:30Z"
    },
    {
      "agent_type": "code-reviewer",
      "session_id": "session-789",
      "step_id": "review",
      "status": "waiting",
      "started_at": "2026-04-02T13:03:00Z",
      "waiting_for": "user_input"
    }
  ],
  "latest_event": {
    "type": "step_completed",
    "step_id": "design",
    "timestamp": "2026-04-02T13:01:45Z"
  }
}
```

## Hook Integration Points

### Swarm CLI Hooks

New hooks in `src/swarm/cli/` to emit HUD events:

1. **plan_start** - Create plan state file when `swarm run` starts
2. **wave_start** - Update current wave counter
3. **step_start** - Add agent to active_agents list
4. **step_complete** - Remove from active_agents, increment completed count
5. **step_failed** - Mark step as failed, update status
6. **plan_complete** - Mark plan as complete, remove state file
7. **plan_cancel** - Mark plan as cancelled

### Orchestrator Session Hooks

The orchestrator session can use existing tmux-statusline hooks but with custom state:

```json
{
  "session_id": "orchestrator-abc",
  "status": "orchestrating",
  "current_activity": "Waiting for wave 2 to complete",
  "plan_run_id": "abc123"
}
```

## Display Scripts

### bin/swarm-hud.py

Python script similar to constellation.py:

```python
#!/usr/bin/env python3
"""
Swarm HUD - Display plan execution state in tmux status bar.

Usage:
  swarm-hud.py                    # Mode 1: Compact progress bar
  swarm-hud.py --expanded         # Mode 2: 2-line dashboard
  swarm-hud.py --per-window       # Mode 3: Per-window badges
  swarm-hud.py --run-id=<id>      # Filter by specific run
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

STATE_DIR = Path.home() / ".swarm-tmux-hud" / "state"

def find_active_plan(tmux_pid: int) -> Optional[dict]:
    """Find the most recent active plan for this tmux session."""
    pid_dir = STATE_DIR / str(tmux_pid)
    if not pid_dir.exists():
        return None

    plan_files = list(pid_dir.glob("plan_*.json"))
    if not plan_files:
        return None

    # Most recent by mtime
    latest = max(plan_files, key=lambda p: p.stat().st_mtime)

    # Ignore if stale (>5 minutes since update)
    if time.time() - latest.stat().st_mtime > 300:
        return None

    with open(latest) as f:
        return json.load(f)

def format_duration(started_at: str) -> str:
    """Format elapsed time since start."""
    start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
    elapsed = datetime.now().astimezone() - start

    total_seconds = int(elapsed.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60

    if minutes > 0:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"

def render_progress_bar(completed: int, total: int, width: int = 40) -> str:
    """Render a Unicode progress bar."""
    if total == 0:
        return "━" * width

    filled = int(width * completed / total)
    empty = width - filled
    return "━" * filled + "╸" + "━" * (empty - 1) if empty > 0 else "━" * width

def render_compact(plan: dict) -> str:
    """Mode 1: Compact single-line display."""
    goal = plan["goal"][:20]
    wave = f"[Wave {plan['current_wave']}/{plan['total_waves']}]"

    completed = plan["steps"]["completed"]
    total = plan["steps"]["total"]
    progress = render_progress_bar(completed, total, width=30)

    # Active agents
    active = plan["active_agents"]
    agent_icons = []
    for a in active[:3]:  # Max 3 to save space
        if a["status"] == "working":
            agent_icons.append("●")
        else:
            agent_icons.append("○")
    agent_display = "".join(agent_icons) if agent_icons else ""

    elapsed = format_duration(plan["started_at"])

    return f"📋 {goal} {wave} {progress} {completed}/{total} [{agent_display}] {elapsed}"

def render_expanded(plan: dict) -> str:
    """Mode 2: 2-line expanded dashboard."""
    line1 = render_compact(plan)

    # Line 2: Agent details
    agents = []
    for a in plan["active_agents"]:
        icon = "🟢" if a["status"] == "working" else "🟡"
        name = a["agent_type"]
        suffix = " (waiting)" if a["status"] == "waiting" else ""
        agents.append(f"{icon} {name}{suffix}")

    line2 = "  " + "  ".join(agents) if agents else "  (no active agents)"

    return line1 + "\n" + line2

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--per-window", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()

    # Get tmux PID
    tmux_pid_str = os.popen("tmux display-message -p '#{pid}'").read().strip()
    if not tmux_pid_str.isdigit():
        return  # Not in tmux

    tmux_pid = int(tmux_pid_str)

    # Find active plan
    plan = find_active_plan(tmux_pid)
    if not plan:
        return  # No active plan

    # Render
    if args.expanded:
        print(render_expanded(plan))
    elif args.per_window:
        # TODO: Implement per-window mode
        pass
    else:
        print(render_compact(plan))

if __name__ == "__main__":
    main()
```

## tmux Configuration

### Mode 1: Dedicated Plan Status Line

Add to `~/.tmux.conf`:

```bash
# Swarm plan execution HUD (adds second status line)
set -g status 3  # Or 2 if not using tmux-statusline constellation
set -g status-format[2] '#(python3 ~/.local/share/swarm/bin/swarm-hud.py)'
```

### Mode 2: Inline in status-right

```bash
set -g status-right '#(python3 ~/.local/share/swarm/bin/swarm-hud.py) | #{host} %H:%M'
```

## Event Emission

### In plan/executor.py

Add HUD event emission to the executor:

```python
from swarm.hud.events import emit_plan_start, emit_wave_start, emit_step_start, emit_step_complete

class PlanExecutor:
    def execute(self, plan: Plan) -> RunResult:
        # Emit plan start
        emit_plan_start(
            run_id=self.run_id,
            plan_path=str(self.plan_path),
            goal=plan.goal,
            total_steps=len(plan.steps),
            total_waves=self._count_waves(plan)
        )

        try:
            for wave_num, wave_steps in enumerate(self._get_execution_waves(plan), 1):
                emit_wave_start(self.run_id, wave_num)

                for step in wave_steps:
                    emit_step_start(
                        run_id=self.run_id,
                        step_id=step.id,
                        agent_type=step.agent_type,
                        session_id=self._session_id_for_step(step)
                    )

                    result = self._execute_step(step)

                    emit_step_complete(
                        run_id=self.run_id,
                        step_id=step.id,
                        success=result.success
                    )
        finally:
            emit_plan_complete(self.run_id)
```

### In src/swarm/hud/events.py

New module for HUD event emission:

```python
"""HUD event emission for tmux status line integration."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

def _get_state_dir() -> Path | None:
    """Get the HUD state directory for the current tmux session."""
    if "TMUX_PANE" not in os.environ:
        return None

    # Get tmux PID
    tmux_pid = os.popen("timeout 1 tmux display-message -p '#{pid}' 2>/dev/null").read().strip()
    if not tmux_pid.isdigit():
        return None

    state_dir = Path.home() / ".swarm-tmux-hud" / "state" / tmux_pid
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir

def _write_plan_state(run_id: str, updates: dict[str, Any]) -> None:
    """Atomically update plan state file."""
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"

    # Read existing state if present
    state = {}
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception:
            pass

    # Merge updates
    state.update(updates)
    state["last_updated"] = datetime.now(UTC).isoformat()

    # Atomic write
    tmp_file = state_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(state, f, indent=2)
    tmp_file.replace(state_file)

def emit_plan_start(
    run_id: str,
    plan_path: str,
    goal: str,
    total_steps: int,
    total_waves: int,
) -> None:
    """Emit plan start event."""
    _write_plan_state(run_id, {
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
            "blocked": 0,
        },
        "active_agents": [],
    })

def emit_wave_start(run_id: str, wave_num: int) -> None:
    """Emit wave start event."""
    _write_plan_state(run_id, {"current_wave": wave_num})

def emit_step_start(
    run_id: str,
    step_id: str,
    agent_type: str,
    session_id: str,
) -> None:
    """Emit step start event."""
    # Read current state to update active_agents list
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"
    if not state_file.exists():
        return

    with open(state_file) as f:
        state = json.load(f)

    # Add to active agents
    state["active_agents"].append({
        "agent_type": agent_type,
        "session_id": session_id,
        "step_id": step_id,
        "status": "working",
        "started_at": datetime.now(UTC).isoformat(),
    })

    # Update counts
    state["steps"]["running"] += 1

    _write_plan_state(run_id, state)

def emit_step_complete(run_id: str, step_id: str, success: bool) -> None:
    """Emit step complete event."""
    state_dir = _get_state_dir()
    if not state_dir:
        return

    state_file = state_dir / f"plan_{run_id}.json"
    if not state_file.exists():
        return

    with open(state_file) as f:
        state = json.load(f)

    # Remove from active agents
    state["active_agents"] = [
        a for a in state["active_agents"]
        if a["step_id"] != step_id
    ]

    # Update counts
    state["steps"]["running"] -= 1
    if success:
        state["steps"]["completed"] += 1

    _write_plan_state(run_id, state)

def emit_plan_complete(run_id: str) -> None:
    """Emit plan complete event."""
    _write_plan_state(run_id, {"status": "complete"})
```

## Installation

Add to install.sh:

```bash
# Install Swarm HUD
echo "Installing Swarm HUD for tmux..."
HUD_DIR="$HOME/.local/share/swarm/bin"
mkdir -p "$HUD_DIR"
cp "$REPO_DIR/src/swarm/hud/swarm-hud.py" "$HUD_DIR/"
chmod +x "$HUD_DIR/swarm-hud.py"
```

## Skill Integration

Add to skills/swarm/SKILL.md:

```markdown
## Swarm HUD (tmux)

If you use tmux, install the Swarm HUD to see plan execution state in your status bar:

\`\`\`bash
# Add to ~/.tmux.conf
set -g status 3
set -g status-format[2] '#(python3 ~/.local/share/swarm/bin/swarm-hud.py)'

# Reload tmux
tmux source ~/.tmux.conf
\`\`\`

Shows:
- Plan progress (6/12 steps)
- Current wave (Wave 2/4)
- Active agents (🟢 working, 🟡 waiting)
- Elapsed time
```

## Benefits Over tmux-statusline Approach

1. **Plan-centric** - Shows orchestration state, not just single agent
2. **Wave-aware** - Visualizes parallel execution waves
3. **Multi-agent** - Track multiple subagents simultaneously
4. **Progress tracking** - Clear X/Y steps complete
5. **Reuses patterns** - Same atomic file write, PID isolation, state directory structure
6. **Complementary** - Can run alongside tmux-statusline for orchestrator session

## Future Enhancements

1. **Critic loop indicators** - Show when a step is in a critic review cycle
2. **Dependency visualization** - Highlight blocked steps waiting for dependencies
3. **Cost tracking** - Aggregate cost across all agents in the plan
4. **Error highlighting** - Flash red on step failures
5. **Retry indicators** - Show retry attempt counts
6. **Background step indicators** - Different icon for background vs foreground steps
7. **Decision step branching** - Show which branches were activated/skipped
8. **Loop iteration counters** - Display current loop iteration
