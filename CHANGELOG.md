# Changelog

All notable changes to Swarm are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows
[SemVer](https://semver.org/).

## [Unreleased]

Round 5 hardening pass plus new docs and examples.

### Round 5 follow-up: critic fixes

Fixes from the Round 5 integration critic — the ten residual HIGH/
MEDIUM/LOW issues spotted after the original hardening commit.

- **HIGH** `agent_send_message` no longer raises
  `sqlite3.IntegrityError` for negotiation message types
  (`proposal`, `counter`, `accept`, `reject`).  The SQLite
  `CHECK (message_type IN (...))` constraint is dropped via an
  idempotent migration that detects the legacy schema in
  `sqlite_master` and rebuilds the table without the clause.  Docs
  in `docs/messaging.md` are now backed by working code.
- **HIGH** `ThreadLocalConnectionPool` registers a
  `weakref.finalize` per worker thread so SQLite handles are closed
  when the thread dies, not when the interpreter exits.  Connections
  use `check_same_thread=False` so the finalizer can run on any
  thread.  Test suite ResourceWarnings dropped from 178 to 0.
- **MEDIUM** `experiment_tools._get_experiment_api()` now asserts on
  the canonical `state.experiment_api` instead of silently spinning
  up a second on-disk database in `plans_dir`.  Mirrors the
  `memory_tools` / `forge_tools` pattern.
- **MEDIUM** `experiments.db` lives at `base_dir / experiments.db`
  for both the MCP server and every CLI command — the lazy
  `plans_dir / experiments.db` divergence is gone, with a comment
  in `cli/_helpers.get_experiments` documenting the canonical path.
- **MEDIUM** `swarm_health` exposes `message_count`,
  `experiment_count`, and `context_count` alongside the existing
  agent / memory / tool counts; `ExperimentAPI.count` and
  `SharedContextAPI.count` were added to back the new fields.
- **MEDIUM** `tests/conftest.py:assert_no_db_leak` lifts the
  `SWARM_SKIP_LEAK_CHECK` env-var check above the snapshot so a
  `return` no longer sits inside `finally` (ruff B012).
- **MEDIUM** `mcp/__init__.list_tools()` now drives FastMCP's public
  async `list_tools()` whenever no event loop is running and only
  falls back to the private `_tool_manager` from inside an active
  loop.  `pyproject.toml` pins `mcp[cli]` to `>=1.0,<2.0` so a
  silent FastMCP rename can't break the health surface.
- **LOW** `swarm experiment assign <name>` CLI subcommand mirrors
  the `experiment_assign_variant` MCP tool for shell-based
  orchestration.
- **LOW** 36 auto-fixable lint errors across `tests/` cleared via
  `ruff check --fix`, plus targeted manual fixes for the
  remaining E741 / B017 / F841 reports.

### Added

- `examples/` directory with three runnable scenarios
  (`research/`, `code-review/`, `incident-response/`) using only base agents,
  fixing the broken doc reference in `docs/writing-plans.md`.
- `docs/memory.md` and `docs/messaging.md` — full reference for the memory
  and inter-agent message bus subsystems.
- Refreshed `docs/writing-plans.md` to cover all step types
  (`task`, `checkpoint`, `loop`, `decision`, `fan_out`, `join`, `subplan`)
  and every PlanStep field.
- Experiment MCP tools (`experiment_create`, `experiment_list`,
  `experiment_get_results`, `experiment_record_result`,
  `experiment_assign_variant`, `experiment_end`) wiring `ExperimentAPI`
  into the MCP server.
- `swarm experiment` CLI subcommand
  (`create`, `list`, `record`, `results`, `end`) for A/B experiment
  management without needing an orchestrator session.
- `swarm update` CLI command — pulls latest code from GitHub and reinstalls.

### Changed

- `ThreadLocalConnectionPool` now backs `MemoryAPI`, `MessageAPI`, and
  `ExperimentAPI` for safe cross-thread SQLite access (Round 5 Wave 2,
  commit `28003a2`).

### Fixed

- Cost-parsing handles missing/malformed `cost_usd` fields without crashing
  the executor.
- Background subprocess PIDs are persisted to the run log for resume after
  crash; orphan detection is now reliable.
- Run-log corruption recovery — atomic writes via `os.replace` plus tolerant
  reload on partial JSON.
- Connection leaks in long-running sessions (Round 5 Wave 1, commit
  `c97f14c`).

## [0.2.0] — 2026-04-09

The big features release. Five tiers of capability landed in nine days.

### Added — Tier 5 (commit `e397e77`, 2026-04-09)

- **Subplans** — `type: "subplan"` step with `subplan_path` field, executes
  a nested plan as a single step.
- **Negotiation threads** — `agent_get_thread` MCP tool walks
  `in_reply_to` chains to reconstruct multi-turn agent conversations.
- **Tracing** — extended event log with structured spans for cross-step
  debugging.

### Added — Tier 4 (commit `e397e77`, 2026-04-09)

- **`plan_remove_step` MCP tool** — surgical step deletion with dependency
  validation.
- **`forge_export_subagent` / `forge_import_subagents`** — bidirectional
  bridge to Claude Code's `.claude/agents/` directory.
- **`forge_diff` MCP tool** — diff two agent definitions to inspect clones
  vs. originals.

### Added — Tier 3 (commit `8c038f8`, 2026-04-09)

- **Real-time event log** — append-only NDJSON in
  `src/swarm/plan/events.py`, surfaced via `plan_run_events` MCP tool.
- **A/B testing** — `ExperimentAPI` for agent variant comparison with
  traffic splitting, result tracking, and winner determination.
- **Plan versioning** — `plan_v1.json`, `plan_v2.json`, ... auto-numbered
  with `plan_amend`.
- **Template parameter schemas** — `parameter_definitions` block on
  templates with type, required, default, and description metadata.
- **TF-IDF similarity search** — `memory_search_similar` MCP tool, semantic
  recall without external dependencies (`src/swarm/memory/similarity.py`).

### Added — Tier 2 (commit `60508b2`, 2026-04-09)

- **Cost tracking** — per-step `cost_usd` and `tokens_used` recorded in the
  run log.
- **Shared context** — run-scoped blackboard via `context_set`,
  `context_get`, `context_get_all`, `context_delete` MCP tools.
- **Agent metrics** — `registry_record_metric` and `registry_get_metrics`
  for usage/failure/cost rollups per agent.
- **Parallel execution** — DAG executor spawns parallel waves, no longer
  serial.
- **Message correlation** — `in_reply_to` field on `AgentMessage` plus
  `agent_reply_message` and `agent_acknowledge_message` MCP tools.

### Added — Tier 1 (commit `fc6a0b7`, 2026-04-09)

- **Per-step timeouts** — `timeout` field on PlanStep (seconds, 0 = none).
- **Agent lifecycle states** — `running`, `succeeded`, `failed`, `cancelled`
  tracked in the run log.
- **Success rate** — derived metric on agents in the registry.
- **Memory injection** — recalled memories formatted as a system-prompt
  block via `format_memories_for_prompt`
  (`src/swarm/memory/injection.py`).
- **Memory reinforcement** — `memory_reinforce` MCP tool boosts relevance
  to counteract decay.

### Added — Plan engine (commit `baaef4e`, 2026-04-02)

- Loop steps with `loop_config` (condition + max_iterations safety net).
- Decision steps with `decision_config` (conditional fan-out via
  `ConditionalAction`).
- Fan-out / join steps for parallel branching.
- Critic loops via `critic_agent` and `max_critic_iterations` fields.
- Retry policies with exponential backoff (`RetryConfig`).
- Conditional gating via `condition` field
  (`always`, `never`, `artifact_exists:`, `step_completed:`,
  `step_failed:`, `iteration_ge:`, `output_contains:`).
- 12 built-in plan templates in `src/swarm/plan/builtin_templates/`.

### Added — Other 0.2.0 changes

- Plan visualization (Mermaid + ASCII waves) — commit `5eaf0ad`.
- Autonomous executor with subprocess management, checkpoints, resume —
  commit `c6ca164`.
- `/swarm` skill for Claude Code integration — commit `9afae6d`.
- FTS5 full-text search on the registry with graceful LIKE fallback —
  commit `41f5114`.

### Changed

- Minimum Python version raised from 3.10 to 3.12 (then back to 3.12 in
  commit `78eb7b1`).
- Documentation rewritten to reflect the new feature surface — commits
  `3f1a2ac`, `11c8165`, `338c423`.

### Removed

- Swarm HUD tmux integration (commit `d9d1dd8`) — split out for separate
  iteration.
- Stale design / planning docs (commit `05c4500`).

## [0.1.0] — 2026-03-29

Initial release. Foundational subsystems and the agent catalog.

### Added

- **Agent catalog** — 66 curated base agents across three domains
  (Technical 24, General 28, Business 14) with auto-seeding on first
  launch (`src/swarm/catalog/`).
- **Registry** — persistent SQLite agent store with FTS5 search,
  source plugins, usage and failure tracking (`src/swarm/registry/`).
- **Forge** — create, clone, search, export/import, annotate agent
  definitions; semantic re-ranking for suggestion (`src/swarm/forge/`).
- **Plan executor** — DAG execution with retry, critic loops, loops, and
  checkpoints (`src/swarm/plan/executor.py`,
  `src/swarm/plan/launcher.py`).
- **Memory subsystem** — episodic / semantic / procedural memory with
  exponential decay, FTS5 recall, and reinforcement
  (`src/swarm/memory/`).
- **Messaging subsystem** — run-scoped inter-agent message bus
  (`src/swarm/messaging/`).
- **MCP server** with ~57 tools across forge, plan, executor, registry,
  artifacts, discovery, memory, messaging, and context categories
  (`src/swarm/mcp/`).
- **CLI** — `swarm`, `swarm forge`, `swarm catalog`, `swarm run`,
  `swarm status`, `swarm registry`, `swarm plan`, `swarm sync`,
  `swarm mcp-config`, `swarm ls` (`src/swarm/cli/`).
- **14 CLI improvements** for streamlined multi-agent workflows
  (commit `b5c4408`, 2026-03-28).

[Unreleased]: https://github.com/anthropics/swarm/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/anthropics/swarm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/anthropics/swarm/releases/tag/v0.1.0
