---
name: swarm
description: "Multi-agent orchestration with Swarm MCP tools - agent forge, registry, plan execution, memory, and messaging"
user-invocable: true
---

# Swarm - Multi-Agent Orchestration

Swarm extends Claude Code with 45 MCP tools for multi-agent orchestration. Use this when you need to:
- Design and manage specialized agents
- Build DAG-based execution plans
- Execute complex multi-step workflows with subagents
- Coordinate agent memory and inter-agent communication

## Quick Start

```bash
# Launch orchestrator session with Swarm MCP tools
swarm

# Launch agent design session
swarm forge

# Execute a plan
swarm run --latest
```

## Core Workflows

### 1. Discover & Select Agents

Use lightweight discovery first, then get full details:

```
swarm_discover("python testing")  # Browse catalog
forge_get("test-writer")          # Get full definition
```

For semantic ranking when multiple agents match:

```
forge_suggest_ranked("review security of API endpoints")
```

### 2. Create Specialized Agents

Start from the 66 base agents, then clone and customize:

```
forge_clone(
  agent_id="base-code-reviewer",
  new_name="api-security-reviewer",
  system_prompt="Focus on authentication, authorization, input validation...",
  tags=["security", "api", "python"]
)
```

### 3. Build Execution Plans

Use templates for common patterns:

```
plan_template_list()  # 12 built-in templates
plan_template_instantiate(
  template_name="code-review",
  variables={"project": "auth-service", "focus": "security"}
)
```

Or create custom plans with advanced features:

```json
{
  "version": 1,
  "goal": "Implement and validate API security",
  "steps": [
    {
      "id": "analyze",
      "type": "task",
      "agent_type": "security-auditor",
      "prompt": "Analyze authentication flows",
      "output_artifact": "security-analysis.md"
    },
    {
      "id": "checkpoint",
      "type": "checkpoint",
      "prompt": "Review security analysis",
      "depends_on": ["analyze"],
      "checkpoint_config": {"message": "Approve security findings?"}
    },
    {
      "id": "implement",
      "type": "task",
      "agent_type": "implementer",
      "prompt": "Implement security fixes",
      "depends_on": ["checkpoint"],
      "condition": "step_completed:checkpoint",
      "critic_agent": "security-auditor",
      "max_critic_iterations": 3,
      "retry_config": {
        "max_retries": 3,
        "backoff_seconds": 2.0,
        "backoff_multiplier": 2.0
      }
    },
    {
      "id": "validate",
      "type": "task",
      "agent_type": "test-writer",
      "prompt": "Write security tests",
      "depends_on": ["implement"],
      "spawn_mode": "background",
      "on_failure": "retry"
    }
  ]
}
```

### 4. Execute Plans

Interactive execution with monitoring:

```
plan_run(plan_path="plan_v1.json")
plan_run_status()  # Check progress
plan_run_resume()  # Resume after crash
```

Or use CLI for autonomous execution:

```bash
swarm run --latest           # Auto-pick latest version
swarm status --diagnose      # Failure analysis
```

### 5. Agent Memory & Messaging

Store and recall agent memories with time-based decay:

```
memory_store(
  agent_name="researcher",
  memory_type="semantic",
  content="API endpoints use JWT tokens with 1hr expiry",
  tags=["auth", "jwt"]
)

memory_recall(
  agent_name="researcher",
  query="authentication",
  limit=5
)
```

Inter-agent communication:

```
agent_send_message(
  from_agent="researcher",
  to_agent="implementer",
  content="Found XSS vulnerability in login form"
)

agent_broadcast(
  from_agent="architect",
  content="Design review complete, proceed with implementation"
)
```

### 6. Close the Feedback Loop

After execution, analyze and improve agents:

```
plan_retrospective(run_log_path="run_log.json")
forge_annotate_from_run(run_log_path="run_log.json")
```

## Advanced Features

### Conditional Step Gating

Control when steps execute based on conditions:

```json
{
  "id": "deploy",
  "condition": "step_completed:all-tests-pass",
  "prompt": "Deploy to production"
}
```

Conditions: `always`, `never`, `artifact_exists:<path>`, `step_completed:<id>`, `step_failed:<id>`

### Loop Steps

Repeated execution with termination conditions:

```json
{
  "id": "polish",
  "type": "loop",
  "loop_config": {
    "condition": "artifact_exists:review-approved",
    "max_iterations": 5
  },
  "prompt": "Improve code quality"
}
```

Note: Loop continues while condition is False, terminates when True.

### Decision Steps

Inline branching logic:

```json
{
  "id": "decide",
  "type": "decision",
  "decision_config": {
    "actions": [
      {
        "condition": "artifact_exists:critical-issues.txt",
        "skip_steps": ["deploy"],
        "activate_steps": ["fix-issues"]
      }
    ]
  }
}
```

### Critic Loops

Automatic quality review cycles:

```json
{
  "id": "implement-feature",
  "agent_type": "implementer",
  "critic_agent": "code-reviewer",
  "max_critic_iterations": 3,
  "prompt": "Implement user authentication"
}
```

### Fan-out/Join

Parallel agent execution:

```json
{
  "id": "parallel-research",
  "type": "fan_out",
  "fan_out_config": {
    "branches": [
      {"agent_type": "researcher", "prompt": "Research auth methods"},
      {"agent_type": "researcher", "prompt": "Research rate limiting"},
      {"agent_type": "researcher", "prompt": "Research audit logging"}
    ]
  }
}
```

### Claude Code Integration

Export agents to Claude Code's native format:

```
forge_export_subagent(agent_id="...", output_dir=".claude/agents")
```

Import from `.claude/agents/*.md`:

```
forge_import_subagents(project_dir=".")
```

## Tool Categories (45 tools)

- **Discovery (1)**: `swarm_discover`
- **Forge (11)**: create, clone, get, list, suggest, suggest_ranked, remove, export_subagent, import_subagents, annotate_from_run
- **Plan (14)**: create, validate, load, list, get_ready_steps, get_step, execute_step, validate_policies, amend, patch_step, template_list, template_instantiate, retrospective, visualize, replan
- **Executor (4)**: plan_run, plan_run_status, plan_run_resume, plan_run_cancel
- **Registry (5)**: list, inspect, search, search_ranked, remove
- **Artifacts (3)**: declare, list, get
- **Memory (4)**: store, recall, forget, prune
- **Messaging (3)**: send_message, receive_messages, broadcast

## Base Agent Catalog

66 base agents across 3 domains:

- **Technical (24)**: architect, code-reviewer, test-writer, debugger, security-auditor, devops-engineer, data-engineer, ml-engineer, etc.
- **General (28)**: researcher, writer, editor, analyst, coordinator, facilitator, coach, trainer, etc.
- **Business (14)**: product-manager, sales-strategist, marketing-strategist, financial-analyst, operations-manager, etc.

Browse with:
```bash
swarm catalog list
swarm catalog search "security"
swarm catalog show code-reviewer
```

## Best Practices

1. **Start with discovery**: Use `swarm_discover` before creating new agents
2. **Clone, don't create**: Start from base agents and specialize
3. **Use templates**: 12 built-in templates for common workflows
4. **Conditional gating**: Control flow with conditions, not just dependencies
5. **Critic loops**: Add automatic quality review for critical steps
6. **Memory decay**: Agents remember recent context better (exponential decay)
7. **Feedback loop**: Run retrospectives and annotate agents after runs
8. **FTS5 search**: Full-text search works across agent names, descriptions, prompts, and tags

## Configuration

```json
{
  "mcpServers": {
    "swarm": {
      "command": "uvx",
      "args": ["--from", "/path/to/swarm", "swarm-mcp"]
    }
  }
}
```

## Common Patterns

### Iterative Refinement
```
plan_template_instantiate("iterative-refinement", {"goal": "polish docs"})
```

### Incident Response
```
plan_template_instantiate("incident-response", {"severity": "high"})
```

### Code Review Pipeline
```
plan_template_instantiate("code-review", {"focus": "security"})
```

### Parallel Research
```
plan_template_instantiate("parallel-research", {"topics": "auth,logging,monitoring"})
```

## Troubleshooting

### Agent not found
Use `swarm_discover` to browse available agents first.

### Step blocked
Check conditions with `plan_get_ready_steps` and verify artifacts exist.

### Run crashed
Resume with `plan_run_resume()` - checkpoint recovery is automatic.

### Poor agent selection
Use `forge_suggest_ranked` for semantic ranking instead of `forge_suggest`.

### Memory not recalled
Check time decay - memories older than 30 days have exponentially lower relevance.

## Swarm HUD (tmux)

If you use tmux, Swarm includes a heads-up display to visualize plan execution in your status bar.

### Setup

Add to `~/.tmux.conf`:

```bash
# Swarm plan execution HUD (adds a status line)
set -g status 3
set -g status-format[2] '#(python3 ~/.local/share/swarm/bin/swarm-hud.py)'
```

Reload tmux:
```bash
tmux source ~/.tmux.conf
```

### What It Shows

**Compact mode (default):**
```
📋 Build API security [Wave 2/4] ━━━━━━━╸━━━━━━━ 6/12 [●●○] 3m15s
```

Components:
- `📋` - Plan icon (✅ complete, ❌ failed)
- Goal - Truncated plan goal
- `[Wave 2/4]` - Current/total execution waves
- Progress bar - Visual step completion
- `6/12` - Steps completed/total
- `[●●○]` - Active agents (● working, ○ waiting)
- `3m15s` - Elapsed time

**Expanded mode:**
```
📋 Build API security | Wave 2/4 | 6/12 steps | ⏱ 3m15s
  🟢 implementer  🟢 test-writer  🟡 code-reviewer (waiting)
```

Use: `swarm-hud.py --expanded`

### Display Modes

- **Mode 1**: `swarm-hud.py` - Compact progress bar (default)
- **Mode 2**: `swarm-hud.py --expanded` - 2-line dashboard
- **Mode 3**: `swarm-hud.py --per-window` - Per-window badges (experimental)

### Combined with Agent Constellation

Swarm HUD complements the tmux-statusline agent constellation:

```
[1:🟢] [2:🟢] [3:🟡 30s]                          Agent States
📋 Build API security [Wave 2/4] ━━━╸━━━ 6/12 [●●○] 3m15s  Plan State
```

Top line: Individual agent status (from tmux-statusline plugin)
Bottom line: Plan orchestration (Swarm HUD)

## Learn More

- **Full catalog**: `swarm catalog list`
- **Plan templates**: `plan_template_list()`
- **Tool reference**: See README.md
- **Plan guide**: docs/writing-plans.md
