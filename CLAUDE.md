# Swarm — Project Instructions

## What is Swarm
Swarm is an MCP tool server and agent registry that extends Claude Code for multi-agent orchestration. It provides 31 MCP tools for designing specialized agents, managing a persistent agent catalog, building DAG-based execution plans with conditions and parallel execution, and closing the feedback loop — all accessible inside a Claude Code session.

## Tech Stack
- **Language**: Python 3.13+
- **Package manager**: uv
- **Build system**: hatchling via pyproject.toml
- **Project layout**: `src/swarm/` (src layout)
- **Testing**: pytest + pytest-asyncio + pytest-mock + pytest-cov (863 tests)
- **Linting**: ruff
- **Typing**: mypy strict mode
- **MCP framework**: mcp[cli] with FastMCP
- **CLI**: click
- **Logging**: structlog (stderr only)
- **Databases**: SQLite (stdlib sqlite3, WAL mode)

## Architecture
Swarm is an MCP server (`swarm-mcp`) that Claude Code connects to. The CLI (`swarm`) can either launch an interactive Claude session with tools attached or run CRUD commands directly.

Key subsystems:
- **Forge** (`src/swarm/forge/`) — create, clone, search, export/import, annotate agent definitions
- **Catalog** (`src/swarm/catalog/`) — 66 base agents across 3 domains, auto-seeding, CLI
- **Registry** (`src/swarm/registry/`) — persistent SQLite agent catalog with source plugins
- **Plan** (`src/swarm/plan/`) — DAG-based execution plans with conditions, fan-out, critic loops, templates, versioning
- **MCP Server** (`src/swarm/mcp/`) — 31 FastMCP tools for forge, plan, registry, artifacts, discovery
- **CLI** (`src/swarm/cli/`) — Click commands + Claude session launcher

Key modules:
- `forge/frontmatter.py` — YAML frontmatter parser/renderer for Claude Code subagent `.md` files
- `forge/ranking.py` — Semantic re-ranking (LLM-agnostic) for agent suggestion
- `catalog/seed.py` — Automatic base agent seeding on first launch
- `catalog/technical.py` — 24 technical domain base agents
- `catalog/general.py` — 28 general-purpose domain base agents
- `catalog/business.py` — 14 business domain base agents
- `plan/conditions.py` — Conditional step gating (artifact_exists, step_completed, step_failed)
- `plan/templates.py` — Plan template system with built-in templates
- `mcp/discovery_tools.py` — Lightweight agent catalog browsing
- `cli/catalog_cmd.py` — Catalog list/search/inspect/clone commands

## Conventions
- Use `pathlib.Path` throughout, never string paths
- All tests use `tmp_path` fixtures — never touch the real filesystem
- Frozen dataclasses for immutable data models
- Type annotations on all public functions
- Tests go in `tests/` mirroring the src structure
- SQLite databases use WAL mode with idempotent ALTER TABLE migrations
- Agent definitions are immutable — modifications create clones with provenance (`parent_id` chain)
- Clone resets `usage_count`/`failure_count` to 0 but preserves `notes`
- MCP tools accept string params and return JSON strings
- PlanStep uses sparse serialization in `to_dict()` — only non-default fields are emitted
- Plan templates use `{variable}` interpolation with safe regex replacement (unknown placeholders left intact)

## Running
```bash
uv sync                              # install deps
uv run pytest tests/ -v              # run all tests (863 tests)
uv run ruff check src/               # lint
uv run mypy src/                     # type check (strict)
uv run swarm --help                  # CLI entry point
uv run swarm                         # launch orchestrator Claude session
uv run swarm forge                   # launch forge Claude session
uv run swarm catalog list            # list all 66 base agents
uv run swarm catalog search "python" # search base agents
uv run swarm catalog show code-reviewer  # full details of a base agent
uv run swarm catalog seed              # manually seed/refresh base agents
uv run swarm run --latest --dry-run  # preview plan execution waves
uv run swarm status --diagnose       # failure analysis for current run
```
