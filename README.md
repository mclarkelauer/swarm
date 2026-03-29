# Swarm

Swarm extends Claude Code for multi-agent orchestration. It provides an MCP tool server with an agent forge, persistent registry, and DAG-based plan system — all accessible as tools inside a Claude Code session.

Instead of building its own UI, Swarm uses Claude Code as the orchestrator. You describe a goal, Claude breaks it into specialized agent roles, creates them in the forge, builds an execution plan, and spawns subagents to do the work. After each run, the feedback loop closes: retrospective analysis feeds performance data back into agent definitions, so the system improves over time.

## Quick Start

```bash
# Install
git clone <repo-url> && cd swarm
./install.sh

# Launch the orchestrator — Claude with Swarm tools attached
swarm
```

That's it. You're in a Claude Code session with 31 MCP tools for agent management, plan building, and execution. Describe your goal and the orchestrator will:

1. Discover existing agents and suggest matches (`swarm_discover`, `forge_suggest_ranked`)
2. Create specialized agents with focused system prompts, descriptions, and tags
3. Build a DAG execution plan (or instantiate a template)
4. Review the plan with you, then execute steps with subagents
5. Analyze results and annotate agents with performance data

### Other entry points

```bash
swarm forge                      # forge session — design and manage agents
swarm forge suggest "test"       # search for matching agents
swarm ls                         # list agents and plans in current directory
swarm run plan_v1.json           # walk a plan's DAG interactively
swarm run --latest --dry-run     # preview execution waves without running
swarm status                     # show run progress from run_log.json
swarm status --diagnose          # failure analysis with suggested fixes
swarm mcp-config                 # print MCP config for manual setup
```

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code)

## Base Agent Catalog

Swarm ships with **66 curated base agents** across three domains — Technical (24), General (28), and Business (14) — ready to clone and specialize for your projects.

Instead of designing agents from scratch, start with a base agent and customize it:

```bash
# List all base agents
swarm catalog list

# Search for an agent
swarm catalog search "code review"

# Show details and specialization guidance
swarm catalog show code-reviewer
```

### Example Base Agents

**Technical**: `architect`, `code-reviewer`, `test-writer`, `security-auditor`, `devops-engineer`, `technical-writer`

**General**: `project-coordinator`, `business-analyst`, `financial-analyst`, `creative-writer`, `decision-analyst`, `coach`

**Business**: `product-manager`, `sales-strategist`, `marketing-strategist`, `growth-strategist`, `operations-manager`

Once cloned, specialize the agent by refining the system prompt, adding domain-specific tools, and tuning performance. The feedback loop tracks usage and failures, so specialized agents improve over time.

For the full catalog with all 66 agents, see [design.md](design.md#base-agent-catalog).

## How It Works

```
 You
  |
  v
Claude Code (orchestrator)
  |
  ├── Swarm MCP Server (31 tools)
  |     ├── Discovery    — swarm_discover, forge_suggest_ranked
  |     ├── Forge        — create, clone, export, import, annotate agents
  |     ├── Plan         — templates, create, amend, execute, retrospective
  |     ├── Registry     — browse, inspect, search the agent catalog
  |     └── Artifacts    — declare, list, query step outputs
  |
  └── Subagents (spawned by Claude Code)
        ├── researcher    — with forge-defined system prompt
        ├── implementer   — with forge-defined system prompt
        ├── reviewer      — with forge-defined system prompt (critic loop)
        └── ...
```

The orchestrator over-specializes by default. Every distinct skill becomes its own agent with a focused system prompt. When a skill is missing from the registry, the orchestrator proposes creating a new agent and shows you alternatives from the catalog first.

### The Feedback Loop

Swarm agents improve over time. After a plan run:

1. `plan_retrospective` analyzes the run: slowest steps, failing agents, unused artifacts
2. `forge_annotate_from_run` clones agents with updated performance stats and failure notes
3. Next time, `forge_suggest_ranked` factors in reliability data when suggesting agents

Agent definitions are immutable — modifications create clones with provenance tracking (`parent_id` chain), so you can always trace how an agent evolved.

## CLI Reference

```
swarm                               Launch orchestrator session
swarm ls                            Show agents and plans in current directory

swarm forge                         Launch forge session (agent design)
swarm forge design <task>           One-shot agent design via Claude
swarm forge suggest <query>         Search for matching agents
swarm forge edit <name>             Edit agent prompt in $EDITOR (creates clone)
swarm forge export <name>           Export to .agent.json file
swarm forge import <file>           Import from .agent.json file

swarm plan validate <file>          Validate a plan JSON file
swarm plan list [--dir .]           List plan versions in a directory
swarm plan show <file>              Display a plan's DAG structure

swarm run <file>                    Walk a plan's DAG interactively
swarm run --latest                  Auto-pick the highest version plan
swarm run --latest --dry-run        Preview execution waves without running

swarm status                        Show run progress from run_log.json
swarm status --diagnose             Failure analysis with blocked steps and fixes

swarm registry list                 List all registered agents
swarm registry search <query>       Search by name, description, or tags
swarm registry inspect <id>         Full details + provenance chain
swarm registry create               Create a new agent definition
swarm registry clone <id>           Clone with overrides
swarm registry remove <id>          Remove an agent

swarm catalog                       List all base agents (alias for catalog list)
swarm catalog list                  List base agents grouped by domain
swarm catalog search <query>        Search base agents by name, description, or tags
swarm catalog show <name>           Full details and specialization notes
swarm catalog seed                  Manually seed/refresh base agents in registry

swarm sync                          Import .swarm/agents/ into registry
swarm mcp-config                    Print MCP server config for Claude Code
```

## MCP Tools (31 total)

### Discover & Select Agents
| Tool | Description |
|------|-------------|
| `swarm_discover` | Lightweight catalog: name + description + tags + usage stats |
| `forge_suggest` | Search registry + source plugins for matching agents |
| `forge_suggest_ranked` | Semantic ranking with LLM re-ranking prompt |
| `forge_get` | Full agent definition by ID or name |
| `forge_list` | All definitions (system_prompt truncated to 80 chars) |

### Create & Manage Agents
| Tool | Description |
|------|-------------|
| `forge_create` | New agent with name, prompt, tools, description, tags, notes |
| `forge_clone` | Clone with overrides; preserves notes, resets usage counts |
| `forge_remove` | Remove from registry |
| `forge_export_subagent` | Export to `.claude/agents/<name>.md` (Claude Code native format) |
| `forge_import_subagents` | Import `.claude/agents/*.md` into Swarm registry |
| `forge_annotate_from_run` | Update agents with performance data from a run log |

### Build & Modify Plans
| Tool | Description |
|------|-------------|
| `plan_template_list` | List available plan templates |
| `plan_template_instantiate` | Instantiate a template with variables |
| `plan_create` | Create and validate a new plan |
| `plan_validate` | Validate without saving |
| `plan_validate_policies` | Check tool policy compliance against registry |
| `plan_amend` | Splice new steps into an existing plan mid-run |
| `plan_patch_step` | Update a single step without changing DAG structure |
| `plan_load` | Load a plan from disk |
| `plan_list` | List plan versions in a directory |

### Execute & Monitor
| Tool | Description |
|------|-------------|
| `plan_execute_step` | Resolve agent + interpolate variables into invocation payload |
| `plan_get_ready_steps` | DAG-ready steps with condition and artifact gating |
| `plan_get_step` | Single step details |
| `plan_retrospective` | Post-run analysis: slowest steps, failing agents, suggestions |
| `artifact_declare` | Declare a file as a step output |
| `artifact_list` | List all declared artifacts |
| `artifact_get` | Read artifact content + metadata |

### Registry (low-level)
| Tool | Description |
|------|-------------|
| `registry_list` | List all registered agents |
| `registry_inspect` | Full details + provenance chain |
| `registry_search` | Search by name, description, or tags |
| `registry_remove` | Remove an agent |

## Plan Format

Plans are JSON files defining a DAG of steps:

```json
{
  "version": 1,
  "goal": "Build feature: user authentication",
  "variables": {"description": "JWT-based auth", "project_dir": "."},
  "steps": [
    {"id": "design", "type": "task", "agent_type": "architect",
     "prompt": "Design {description}", "output_artifact": "design.md"},
    {"id": "review-design", "type": "checkpoint",
     "prompt": "Review design", "depends_on": ["design"],
     "checkpoint_config": {"message": "Review design.md before implementing."}},
    {"id": "implement", "type": "task", "agent_type": "implementer",
     "prompt": "Implement per design.md", "depends_on": ["review-design"],
     "required_inputs": ["design.md"], "output_artifact": "impl-complete",
     "critic_agent": "code-reviewer", "max_critic_iterations": 3},
    {"id": "test", "type": "task", "agent_type": "test-writer",
     "prompt": "Write tests", "depends_on": ["implement"],
     "spawn_mode": "background", "on_failure": "retry"}
  ]
}
```

### Step Types

| Type | Description |
|------|-------------|
| `task` | Agent does work. Supports `critic_agent` for automatic quality review loops. |
| `checkpoint` | Pause for user review before continuing. |
| `loop` | Repeated execution with termination conditions. |
| `fan_out` | Spawn multiple agents in parallel (requires `fan_out_config`). |
| `join` | Collect results from parallel branches. |

### Step Fields

| Field | Description |
|-------|-------------|
| `output_artifact` | File path this step produces |
| `required_inputs` | Artifact paths that must exist before this step runs |
| `on_failure` | `stop` (default), `skip`, or `retry` |
| `spawn_mode` | `foreground` (default) or `background` |
| `condition` | Gating expression: `artifact_exists:<path>`, `step_completed:<id>`, `step_failed:<id>`, `always`, `never` |
| `critic_agent` | Agent type that reviews this step's output (task steps only) |
| `required_tools` | Tools this step needs (validated against agent's tool list) |

### Built-in Templates

```bash
# List and instantiate templates via MCP tools in a Claude session:
# plan_template_list, plan_template_instantiate
```

Ships with 6 templates: `business-plan`, `code-review`, `feature-build`, `hiring-pipeline`, `product-launch`, `security-audit`.

## Agent Definition

Agents are stored in a SQLite registry with these fields:

| Field | Description |
|-------|-------------|
| `name` | Agent type name (e.g. `code-reviewer`) |
| `description` | One-sentence summary for discovery |
| `system_prompt` | Full instructions for the agent |
| `tools` | Allowed tools (e.g. `["Read", "Write"]`) |
| `tags` | Categorical labels (e.g. `["python", "review"]`) |
| `notes` | Lessons learned, behavioral guidance |
| `usage_count` | Total times used across runs |
| `failure_count` | Total failures across runs |
| `parent_id` | Provenance — which agent this was cloned from |

Agents can also be exported to Claude Code's native `.claude/agents/<name>.md` format via `forge_export_subagent`, and imported back via `forge_import_subagents`.

## Configuration

`~/.swarm/config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `base_dir` | `~/.swarm` | Root directory for Swarm data |
| `forge_timeout` | `600` | Timeout for forge design commands (seconds) |

## Directory Structure

```
~/.swarm/
  config.json           # Configuration
  registry.db           # Persistent agent catalog (SQLite)
  forge/                # Cached agent definitions
  templates/            # User plan templates (override built-ins)
  run/                  # Runtime MCP config

<project>/
  plan_v{N}.json        # Plan versions
  run_log.json          # Execution log
  artifacts.json        # Declared artifacts
  .swarm/agents/        # Project-local agent definitions
```

## Development

```bash
uv sync                          # Install dependencies
uv run pytest tests/ -v          # Run tests (863 tests)
uv run ruff check src/           # Lint
uv run mypy src/                 # Type check (strict)
```

## Documentation

- [Tier 1 Design](docs/tier1-design.md) — Model enrichment specification
- [Tier 2 Design](docs/tier2-design.md) — Bridge tools specification
- [Tier 3 Design](docs/tier3-design.md) — Smarter execution specification
- [Design Specification](design.md) — Original system design

## Tech Stack

Python 3.13+ | Click | structlog | SQLite (WAL) | FastMCP | Rich
