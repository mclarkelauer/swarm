# Swarm — Project Instructions

## What is Swarm
Swarm is an MCP tool server and agent registry that extends Claude Code for multi-agent orchestration. It provides 57 MCP tools for designing specialized agents, managing a persistent agent catalog with FTS5 full-text search, building and executing DAG-based plans with conditional gating, loop steps, decision branches, fan-out/join, critic loops, retry policies, and dynamic replanning, plus agent memory with time-based decay, inter-agent messaging, and bidirectional Claude Code integration via subagent export/import — all accessible inside a Claude Code session.

## Tech Stack
- **Language**: Python 3.12+
- **Package manager**: uv
- **Build system**: hatchling via pyproject.toml
- **Project layout**: `src/swarm/` (src layout)
- **Testing**: pytest + pytest-asyncio + pytest-mock + pytest-cov (1,473 tests)
- **Linting**: ruff
- **Typing**: mypy strict mode
- **MCP framework**: mcp[cli] with FastMCP
- **CLI**: click
- **Logging**: structlog (stderr only)
- **Databases**: SQLite (stdlib sqlite3, WAL mode)

## Architecture
Swarm is an MCP server (`swarm-mcp`) that Claude Code connects to. The CLI (`swarm`) can either launch an interactive Claude session with tools attached or run CRUD commands directly.

Key subsystems:
- **Forge** (`src/swarm/forge/`) — create, clone, search, export/import, annotate agent definitions; semantic re-ranking for agent suggestion
- **Catalog** (`src/swarm/catalog/`) — 66 base agents across 3 domains (technical, general, business), auto-seeding, CLI commands
- **Registry** (`src/swarm/registry/`) — persistent SQLite agent catalog with FTS5 full-text search (graceful LIKE fallback), source plugins, usage/failure tracking
- **Plan** (`src/swarm/plan/`) — DAG-based execution plans with conditional gating, loop steps, decision branches, fan-out/join, critic loops, retry policies with exponential backoff, 12 built-in templates, versioning
- **Executor** (`src/swarm/plan/executor.py`, `launcher.py`) — autonomous plan execution with subprocess management, retry, loops, checkpoints, resume, and background spawning
- **Context** (`src/swarm/context/`) — run-scoped shared blackboard (key-value store) for inter-agent data sharing within a plan run
- **Memory** (`src/swarm/memory/`) — persistent agent memory (episodic/semantic/procedural) with FTS5 search, TF-IDF similarity search, exponential time-based decay, reinforcement, pruning, and automatic prompt injection
- **Messaging** (`src/swarm/messaging/`) — inter-agent message bus with send, receive, broadcast, reply with correlation IDs, acknowledgment, negotiation threads, message routing (message_to), scoped by run
- **Experiments** (`src/swarm/experiments/`) — A/B testing for agent variants with traffic splitting, result tracking, and winner determination
- **MCP Server** (`src/swarm/mcp/`) — 57 FastMCP tools across 9 categories: forge (12), plan (16), execution (6), registry (8), artifacts (3), discovery (2), memory (6), messaging (6), context (4)
- **CLI** (`src/swarm/cli/`) — Click commands (catalog, run, status, forge) + Claude session launcher with MCP server attachment

Key modules:
- `forge/frontmatter.py` — Minimal YAML frontmatter parser/renderer (~40 lines) for Claude Code subagent `.md` files, no PyYAML dependency
- `forge/ranking.py` — Semantic re-ranking (LLM-agnostic) with build_ranking_prompt() and parse_ranking_response()
- `catalog/seed.py` — Automatic base agent seeding on first launch
- `catalog/technical.py` — 24 technical domain base agents (code-reviewer, test-writer, debugger, etc.)
- `catalog/general.py` — 28 general-purpose domain base agents (researcher, writer, analyzer, etc.)
- `catalog/business.py` — 14 business domain base agents (product-manager, analyst, etc.)
- `plan/models.py` — PlanStep with loop_config, decision_config, critic_agent, retry_config, condition, message_to, timeout, subplan_path fields
- `plan/events.py` — Append-only NDJSON event log for real-time execution progress tracking
- `plan/conditions.py` — Conditional step gating (always, never, artifact_exists:<path>, step_completed:<id>, step_failed:<id>)
- `plan/templates.py` — Plan template system with 12 built-in templates (code-review, data-pipeline, incident-response, iterative-refinement, etc.)
- `plan/executor.py` — Autonomous DAG execution loop with retry, loops, critic cycles, checkpoints, background spawning, crash recovery
- `plan/launcher.py` — Claude CLI subprocess management with timeout and signal handling
- `plan/visualization.py` — Mermaid flowchart and ASCII wave table rendering for plan DAGs
- `plan/dag.py` — DAG analysis with get_ready_steps(), topological sort, wave detection
- `memory/api.py` — Agent memory CRUD with store, recall, recall_similar (TF-IDF), reinforce, forget, decay (exponential: 2^(-days/30)), prune (0.1 threshold)
- `memory/injection.py` — Format recalled memories for system prompt injection
- `memory/similarity.py` — Lightweight TF-IDF cosine similarity search for semantic memory retrieval (no external dependencies)
- `messaging/api.py` — Inter-agent message bus with send, receive, broadcast, reply, acknowledge, get_thread, scoped by run_id
- `context/api.py` — Run-scoped shared context (blackboard) with set, get, get_all, delete, clear operations
- `experiments/api.py` — Agent A/B testing with experiment creation, variant routing, result recording, and winner determination
- `mcp/discovery_tools.py` — Lightweight agent catalog browsing (swarm_discover) and system health check (swarm_health)
- `mcp/executor_tools.py` — Plan execution tools (plan_run, plan_run_status, plan_run_resume, plan_run_cancel, plan_run_events, plan_run_logs)
- `mcp/memory_tools.py` — Memory tools (memory_store, memory_recall, memory_forget, memory_prune, memory_reinforce, memory_search_similar)
- `mcp/message_tools.py` — Messaging tools (agent_send_message, agent_receive_messages, agent_broadcast, agent_reply_message, agent_acknowledge_message, agent_get_thread)
- `mcp/context_tools.py` — Shared context tools (context_set, context_get, context_get_all, context_delete)
- `mcp/forge_tools.py` — 12 forge tools including forge_export_subagent, forge_import_subagents, forge_suggest_ranked, forge_diff
- `mcp/artifact_tools.py` — Artifact query tools (artifact_declare, artifact_list, artifact_get)
- `mcp/plan_tools.py` — 16 plan tools including plan_execute_step, plan_get_ready_steps, plan_template_instantiate, plan_replan, plan_remove_step
- `mcp/registry_tools.py` — Registry tools with FTS5 search (registry_search, registry_search_ranked, registry_list, registry_inspect, registry_remove, registry_update, registry_record_metric, registry_get_metrics)
- `cli/catalog_cmd.py` — Catalog list/search/inspect/clone commands
- `cli/run_cmd.py` — Plan execution command with --latest flag and --dry-run preview
- `cli/status_cmd.py` — Run status command with --diagnose flag for failure analysis

## Conventions
- Use `pathlib.Path` throughout, never string paths
- All tests use `tmp_path` fixtures — never touch the real filesystem (1,473 tests)
- Frozen dataclasses for immutable data models (Plan, PlanStep, AgentDefinition, etc.)
- Type annotations on all public functions (mypy strict mode)
- Tests go in `tests/` mirroring the src structure
- SQLite databases use WAL mode with idempotent ALTER TABLE migrations
- Agent definitions are immutable — modifications create clones with provenance (`parent_id` chain)
- Clone resets `usage_count`/`failure_count` to 0 but preserves `notes`
- MCP tools accept string params and return JSON strings (MCP convention)
- PlanStep uses sparse serialization in `to_dict()` — only non-default fields are emitted
- Plan templates use `{variable}` interpolation with safe regex replacement (unknown placeholders left intact)
- Agent memory is keyed by `agent_name` (not `agent_id`) since agents are cloned — name is the stable identity
- FTS5 search degrades gracefully to LIKE when the SQLite FTS5 extension is unavailable
- The executor spawns `claude` CLI subprocesses — it never calls an LLM directly (LLM-agnostic design)
- Run logs use atomic writes (`os.replace`) for crash recovery
- Loop steps use inverted condition semantics: loop continues while False, terminates when True
- Decision steps execute inline (no subprocess) — they activate/skip downstream branches via ConditionalAction
- Critic loops use `critic_agent` field with `max_critic_iterations` (default 3) — critic accepts/rejects work
- Retry policies use exponential backoff: delay = backoff_seconds * (backoff_multiplier ^ attempt), capped at max_backoff_seconds
- Conditional gating: `condition` field on PlanStep supports always, never, artifact_exists:<path>, step_completed:<id>, step_failed:<id>
- Messages are scoped per run (`run_id`) by default, with optional message routing via `message_to` field
- Memory decay uses exponential formula: `relevance = 2^(-days / 30)`, pruned at 0.1 threshold
- Frontmatter parser is a minimal custom implementation (~40 lines) — no PyYAML dependency
- Semantic ranking is LLM-agnostic — Swarm builds prompts, orchestrator evaluates them

## Running
```bash
# Development
uv sync                              # install deps
uv run pytest tests/ -v              # run all tests (1,473 tests)
uv run pytest tests/ --cov=src       # run tests with coverage
uv run ruff check src/               # lint
uv run mypy src/                     # type check (strict mode)

# CLI entry points
uv run swarm --help                  # show all commands
uv run swarm                         # launch orchestrator Claude session with MCP server
uv run swarm forge                   # launch forge Claude session (agent design mode)

# Catalog management
uv run swarm catalog list            # list all 66 base agents with usage/failure stats
uv run swarm catalog search "python" # search base agents (FTS5 full-text search)
uv run swarm catalog show code-reviewer  # full details of a base agent
uv run swarm catalog clone code-reviewer my-reviewer  # clone and customize an agent
uv run swarm catalog seed            # manually seed/refresh base agents from built-ins

# Plan execution
uv run swarm run plan_v1.json        # execute a specific plan
uv run swarm run --latest            # auto-detect and execute latest plan version
uv run swarm run --latest --dry-run  # preview plan execution waves without running
uv run swarm run --resume            # resume crashed/interrupted run from checkpoint

# Status and diagnostics
uv run swarm status                  # show current run status (progress, durations)
uv run swarm status --diagnose       # failure analysis with error messages and step outcomes
uv run swarm status --log-file=custom.json  # status for specific run log
```
