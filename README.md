# Swarm

Swarm extends Claude Code for multi-agent orchestration. It provides an MCP tool server with an agent forge, persistent registry, and DAG-based plan system — all accessible as tools inside a Claude Code session.

Instead of building its own UI, Swarm uses Claude Code as the orchestrator. You describe a goal, Claude breaks it into specialized agent roles, creates them in the forge, builds an execution plan, and spawns subagents to do the work.

## Quick Start

```bash
# Install
git clone <repo-url> && cd swarm
./install.sh

# Launch the orchestrator — Claude with Swarm tools attached
swarm
```

That's it. You're in a Claude Code session with forge, plan, and registry tools. Describe your goal and the orchestrator will:

1. Break it into specialized agent roles
2. Search the registry for existing agents, suggest new ones for gaps
3. Create agents with focused system prompts
4. Build a DAG execution plan and review it with you
5. Spawn subagents to execute the plan

### Other entry points

```bash
swarm forge                  # forge session — design and manage agents
swarm forge suggest "test"   # search for matching agents
swarm plan show plan.json    # display a plan's structure
swarm registry list          # list all registered agents
swarm mcp-config             # print MCP config for manual setup
```

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code)

## How It Works

```
 You
  |
  v
Claude Code (orchestrator)
  |
  ├── Swarm MCP Server
  |     ├── Forge tools   — create, clone, search agent definitions
  |     ├── Plan tools    — create, validate, execute DAG plans
  |     ├── Registry tools — browse the persistent agent catalog
  |     └── Artifact tools — declare output files
  |
  └── Subagents (spawned by Claude Code)
        ├── researcher    — with forge-defined system prompt
        ├── implementer   — with forge-defined system prompt
        ├── reviewer      — with forge-defined system prompt
        └── ...
```

The orchestrator over-specializes by default. Every distinct skill becomes its own agent with a focused system prompt. When a skill is missing from the registry, the orchestrator proposes creating a new agent and shows you alternatives from the catalog first.

## CLI Reference

```
swarm                           Launch orchestrator session
swarm forge                     Launch forge session (agent design)
swarm forge design <task>       One-shot agent design via Claude
swarm forge suggest <query>     Search for matching agents

swarm plan validate <file>      Validate a plan JSON file
swarm plan list [--dir .]       List plan versions in a directory
swarm plan show <file>          Display a plan's DAG structure

swarm registry list             List all registered agents
swarm registry search <query>   Search by name or prompt
swarm registry inspect <id>     Full details + provenance chain
swarm registry create           Create a new agent definition
swarm registry clone <id>       Clone with overrides
swarm registry remove <id>      Remove an agent

swarm mcp-config                Print MCP server config for Claude Code
swarm mcp-config --json-file    Full config file for --mcp-config flag
```

## Plan Format

Plans are JSON files defining a DAG of steps:

```json
{
  "version": 1,
  "goal": "Research and write a technical proposal",
  "variables": {"topic": "distributed systems"},
  "steps": [
    {"id": "research", "type": "task", "agent_type": "researcher",
     "prompt": "Research {topic}", "depends_on": []},
    {"id": "review", "type": "checkpoint",
     "prompt": "Review research before writing", "depends_on": ["research"]},
    {"id": "write", "type": "task", "agent_type": "writer",
     "prompt": "Write proposal based on research", "depends_on": ["review"]}
  ]
}
```

Step types: **task** (agent does work), **checkpoint** (pause for user review), **loop** (repeated execution).

See [docs/writing-plans.md](docs/writing-plans.md) for the full plan authoring guide.

## Configuration

`~/.swarm/config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `base_dir` | `~/.swarm` | Root directory for Swarm data |
| `forge_timeout` | `600` | Timeout for forge design commands (seconds) |

## Directory Structure

```
~/.swarm/
  config.json        # Configuration
  registry.db        # Persistent agent catalog (SQLite)
  forge/             # Cached agent definitions
  run/               # Runtime MCP config
```

Plans are stored in your project directory as `plan_v{N}.json`.

## Development

```bash
uv sync                          # Install dependencies
uv run pytest tests/ -v          # Run tests (213 tests)
uv run ruff check src/           # Lint
uv run mypy                      # Type check (strict)
```

## Documentation

- [Writing Plans](docs/writing-plans.md) — Plan JSON format, step types, DAG patterns
- [Design Specification](design.md) — Full system design

## Tech Stack

Python 3.13+ | Click | structlog | SQLite (WAL) | FastMCP | Rich
