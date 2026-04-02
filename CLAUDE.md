# Swarm — Project Instructions

## What is Swarm
Swarm is an MCP tool server and agent registry that extends Claude Code for multi-agent orchestration. It provides 45 MCP tools for designing specialized agents, managing a persistent agent catalog, building and executing DAG-based plans with conditions, fan-out/join, critic loops, and dynamic replanning, plus agent memory and inter-agent messaging — all accessible inside a Claude Code session.

## Tech Stack
- **Language**: Python 3.13+
- **Package manager**: uv
- **Build system**: hatchling via pyproject.toml
- **Project layout**: `src/swarm/` (src layout)
- **Testing**: pytest + pytest-asyncio + pytest-mock + pytest-cov (1,272 tests)
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
- **Registry** (`src/swarm/registry/`) — persistent SQLite agent catalog with FTS5 full-text search and source plugins
- **Plan** (`src/swarm/plan/`) — DAG-based execution plans with conditions, fan-out/join, decision steps, critic loops, templates, versioning
- **Executor** (`src/swarm/plan/executor.py`, `launcher.py`) — autonomous plan execution with subprocess management, retry, loops, checkpoints, and resume
- **Memory** (`src/swarm/memory/`) — persistent agent memory (episodic/semantic/procedural) with FTS5 search, time-based decay, and prompt injection
- **Messaging** (`src/swarm/messaging/`) — inter-agent message bus with send, receive, broadcast, scoped by run
- **MCP Server** (`src/swarm/mcp/`) — 45 FastMCP tools for forge, plan, execution, registry, artifacts, discovery, memory, messaging
- **CLI** (`src/swarm/cli/`) — Click commands + Claude session launcher

Key modules:
- `forge/frontmatter.py` — YAML frontmatter parser/renderer for Claude Code subagent `.md` files
- `forge/ranking.py` — Semantic re-ranking (LLM-agnostic) for agent suggestion
- `catalog/seed.py` — Automatic base agent seeding on first launch
- `catalog/technical.py` — 24 technical domain base agents
- `catalog/general.py` — 28 general-purpose domain base agents
- `catalog/business.py` — 14 business domain base agents
- `plan/conditions.py` — Conditional step gating (artifact_exists, step_completed, step_failed, iteration_ge, output_contains)
- `plan/templates.py` — Plan template system with 12 built-in templates
- `plan/executor.py` — Autonomous DAG execution loop with retry, loops, critic cycles, checkpoints, background spawning
- `plan/launcher.py` — Claude CLI subprocess management with timeout and signal handling
- `plan/visualization.py` — Mermaid flowchart and ASCII wave table rendering for plan DAGs
- `memory/api.py` — Agent memory CRUD with store, recall, forget, decay, prune
- `memory/injection.py` — Format recalled memories for system prompt injection
- `messaging/api.py` — Inter-agent message bus with send, receive, broadcast
- `mcp/discovery_tools.py` — Lightweight agent catalog browsing
- `mcp/executor_tools.py` — Plan execution MCP tools (plan_run, plan_run_status, plan_run_resume, plan_run_cancel)
- `mcp/memory_tools.py` — Memory MCP tools (memory_store, memory_recall, memory_forget, memory_prune)
- `mcp/message_tools.py` — Messaging MCP tools (agent_send_message, agent_receive_messages, agent_broadcast)
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
- Agent memory is keyed by `agent_name` (not `agent_id`) since agents are cloned — name is the stable identity
- FTS5 search degrades gracefully to LIKE when the SQLite FTS5 extension is unavailable
- The executor spawns `claude` CLI subprocesses — it never calls an LLM directly (LLM-agnostic design)
- Run logs use atomic writes (`os.replace`) for crash recovery
- Loop steps use inverted condition semantics: loop continues while False, terminates when True
- Decision steps execute inline (no subprocess) — they activate/skip downstream branches
- Messages are scoped per run (`run_id`) by default
- Memory decay uses exponential formula: `relevance = 2^(-days / 30)`, pruned at 0.1 threshold

## Running
```bash
uv sync                              # install deps
uv run pytest tests/ -v              # run all tests (1,272 tests)
uv run ruff check src/               # lint
uv run mypy src/                     # type check (strict)
uv run swarm --help                  # CLI entry point
uv run swarm                         # launch orchestrator Claude session
uv run swarm forge                   # launch forge Claude session
uv run swarm catalog list            # list all 66 base agents
uv run swarm catalog search "python" # search base agents (FTS5)
uv run swarm catalog show code-reviewer  # full details of a base agent
uv run swarm catalog seed              # manually seed/refresh base agents
uv run swarm run --latest --dry-run  # preview plan execution waves
uv run swarm run --latest            # execute plan interactively
uv run swarm status --diagnose       # failure analysis for current run
```
