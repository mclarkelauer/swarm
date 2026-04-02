# Swarm HUD Visual Mockups

## Mode 1: Compact Progress Bar (Default)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ orchestrator-session                                              09:15:32  │
├─────────────────────────────────────────────────────────────────────────────┤
│ > swarm run --latest                                                        │
│                                                                               │
│ [Swarm executing plan_v1.json...]                                           │
│                                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 📋 Build API security [Wave 2/4] ━━━━━━━━━━━━━━━╸━━━━━━━━━ 6/12 [●●○] 3m15s  │
└─────────────────────────────────────────────────────────────────────────────┘
     Plan goal           Wave info   Progress bar    Steps  Agents Elapsed
```

## Mode 2: Expanded Dashboard (2-line)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ orchestrator-session                                              09:15:32  │
├─────────────────────────────────────────────────────────────────────────────┤
│ > swarm run --latest                                                        │
│                                                                               │
│ [Swarm executing plan_v1.json...]                                           │
│                                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 📋 Build API security | Wave 2/4 | 6/12 steps | ⏱ 3m15s                     │
│   🟢 implementer  🟢 test-writer  🟡 code-reviewer (waiting)                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Mode 3: Per-Window Agent Badges

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 1:orchestrator 📋 | 2:implementer 🟢 | 3:test-writer 🟢 | 4:reviewer 🟡    │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│ Window 2 (implementer agent):                                               │
│ > Implementing authentication middleware...                                 │
│                                                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

## Combined: Swarm HUD + Agent Constellation

Using both tmux-statusline (for individual agents) and Swarm HUD (for plan):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1:orchestrator ⚪ | 2:implementer 🟢 | 3:test-writer 🟢 | 4:reviewer 🟡       │
├─────────────────────────────────────────────────────────────────────────────┤
│ [1:🟢] [2:🟢] [3:🟢] [4:🟡 30s]                                  Agent States │
│ 📋 Build API security [Wave 2/4] ━━━━━━━━╸━━━━━ 6/12 [●●○] 3m15s  Plan State │
└─────────────────────────────────────────────────────────────────────────────┘
     ^                                              ^
     Agent constellation (from tmux-statusline)     Swarm plan HUD (new)
```

## State Transitions

### Plan Start

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 Build API security [Wave 1/4] ━╸━━━━━━━━━━━━━━━━━━━━━ 0/12 [] 0s          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Wave 1: Sequential Steps

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 Build API security [Wave 1/4] ━━━╸━━━━━━━━━━━━━━━━━━━ 2/12 [●] 1m30s      │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                    ^ 1 active
```

### Wave 2: Parallel Execution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 Build API security [Wave 2/4] ━━━━━━━╸━━━━━━━━━━━━━━━ 5/12 [●●●] 2m45s    │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                    ^^^ 3 active
```

### Waiting for User Input

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 Build API security [Wave 2/4] ━━━━━━━━╸━━━━━━━━━━━━━ 6/12 [●●○] 3m15s     │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                    ^^○ 1 waiting
```

### Critic Loop in Progress

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 Build API security [Wave 2/4] ━━━━━━━━━╸━━━━━━━━━━━━ 7/12 [●◉] 4m20s      │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                    ^◉ critic loop
```

### Plan Complete

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ✅ Build API security [Complete] ━━━━━━━━━━━━━━━━━━━━━━━━━ 12/12 [] 8m42s     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plan Failed

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ❌ Build API security [Failed at step 8] ━━━━━━━╸━━━━━━━ 7/12 [✗] 5m15s      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Icon Legend

### Plan Status
- `📋` - Plan running
- `✅` - Plan complete
- `❌` - Plan failed
- `⏸` - Plan paused (checkpoint)

### Agent States (Active Agents)
- `●` - Agent working
- `○` - Agent waiting for user input
- `◉` - Agent in critic loop
- `✗` - Agent failed
- `⟳` - Agent retrying

### Progress Bar
- `━` - Completed portion (filled)
- `╸` - Current position marker
- `━` - Remaining portion (empty)

## Color Coding (tmux)

```bash
# In tmux config, apply colors:
set -g status-format[2] '#[fg=cyan]#(python3 ~/.local/share/swarm/bin/swarm-hud.py --with-colors)'
```

Colors:
- **Cyan** - Plan icon and goal
- **Green** - Progress bar (filled portion)
- **Yellow** - Current wave indicator
- **White** - Step counts
- **Green** `●` - Working agents
- **Yellow** `○` - Waiting agents
- **Red** `◉` - Critic loop
- **Red** `✗` - Failed

## Expanded Mode with Pane Topics

Combine with tmux pane borders to show what each agent is working on:

```
┌ 0: orchestrator 📋 | swarm ──────────────────────────────────────┐
│ > Monitoring plan execution...                                   │
├ 1: implementer 🟢 | implementing auth middleware ────────────────┤
│ > Writing JWT token validation...                                │
├ 2: test-writer 🟢 | writing security tests ──────────────────────┤
│ > Creating test fixtures...                                      │
├ 3: code-reviewer 🟡 | waiting for review approval ───────────────┤
│ > [Waiting for user input]                                       │
└──────────────────────────────────────────────────────────────────┘
📋 Build API security | Wave 2/4 | 6/12 steps | ⏱ 3m15s
  🟢 implementer  🟢 test-writer  🟡 code-reviewer (waiting)
```

## Integration with Agent Metadata

If using tmux-statusline's meta-status feature, show per-pane agent cost:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ opus-4 | 🧠 45% | 💰 $2.15 | 🔄 8                               09:15:32      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [Pane 2: implementer agent session metadata]                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 📋 Build API security [Wave 2/4] ━━━━━━━━╸━━━━━━━ 6/12 [●●○] 3m15s | 💰 $8.50│
└─────────────────────────────────────────────────────────────────────────────┘
     ^ Agent metadata (from tmux-statusline)         ^ Plan cost (aggregated)
```

Shows:
- **Per-agent** cost/context/turns in top line (active pane only)
- **Aggregate plan** cost in HUD line (all agents combined)

## Responsive Design

The HUD adapts to terminal width:

### Wide (120+ columns)
```
📋 Build API security [Wave 2/4] ━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━ 6/12 [●●○] 3m15s
```

### Medium (80-120 columns)
```
📋 API security [2/4] ━━━━━━━╸━━━━━ 6/12 [●●○] 3m15s
```

### Narrow (<80 columns)
```
📋 [2/4] ━━╸━━ 6/12 3m
```
