# Swarm — Project Instructions

## What is Swarm
Swarm is an MCP tool server and agent registry that extends Claude Code for multi-agent orchestration. It provides tools for designing specialized agents, managing an agent catalog, and building DAG-based execution plans — all accessible as MCP tools inside a Claude Code session.

## Tech Stack
- **Language**: Python 3.13+
- **Package manager**: uv
- **Build system**: hatchling via pyproject.toml
- **Project layout**: `src/swarm/` (src layout)
- **Testing**: pytest + pytest-asyncio + pytest-mock + pytest-cov
- **Linting**: ruff
- **Typing**: mypy strict mode
- **MCP framework**: mcp[cli] with FastMCP
- **CLI**: click
- **Logging**: structlog (stderr only)
- **Databases**: SQLite (stdlib sqlite3, WAL mode)

## Architecture
Swarm is an MCP server (`swarm-mcp`) that Claude Code connects to. The CLI (`swarm`) can either launch an interactive Claude session with tools attached or run CRUD commands directly.

Key subsystems:
- **Forge** (`src/swarm/forge/`) — create, clone, search agent definitions
- **Registry** (`src/swarm/registry/`) — persistent SQLite agent catalog with source plugins
- **Plan** (`src/swarm/plan/`) — DAG-based execution plans with versioning
- **MCP Server** (`src/swarm/mcp/`) — FastMCP tools for forge, plan, registry, artifacts
- **CLI** (`src/swarm/cli/`) — Click commands + Claude session launcher

## Conventions
- Use `pathlib.Path` throughout, never string paths
- All tests use `tmp_path` fixtures — never touch the real filesystem
- Frozen dataclasses for immutable data models
- Type annotations on all public functions
- Tests go in `tests/` mirroring the src structure
- SQLite databases use WAL mode
- Agent definitions are immutable — modifications create clones with provenance
- MCP tools accept string params and return JSON strings

## Running
```bash
uv sync                    # install deps
uv run pytest tests/ -v    # run all tests
uv run swarm --help       # CLI entry point
uv run swarm              # launch orchestrator Claude session
uv run swarm forge        # launch forge Claude session
```
