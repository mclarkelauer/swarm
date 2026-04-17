# Agent Memory

Persistent memory for individual agents. An agent can store facts it
learned, recall them in future sessions, and reinforce the ones that
proved useful so they survive time-based decay.

Use it when an agent needs to carry context across runs — e.g. project
conventions, past failures, recurring patterns. Skip it for state that
belongs in the run-scoped shared context (`context_set` / `context_get`)
or in artifacts.

## 5-minute tour

Three operations cover the common case: store, recall, reinforce.

```python
# Store something the agent learned
memory_store(
    agent_name="code-reviewer",
    content="This codebase uses pathlib.Path everywhere; flag str path arguments.",
    memory_type="procedural",
)

# Recall later (in any future run)
memory_recall(agent_name="code-reviewer", query="path handling")

# When a recalled memory contributed to a good outcome, reinforce it
memory_reinforce(memory_id="<uuid>", boost="0.3")
```

That's the end-to-end flow. Memories are keyed by `agent_name` (not
`agent_id`) — see [Gotchas](#gotchas) below for why.

## Concepts

### Memory types

Three flavors, distinguished by what they encode. All three live in the
same SQLite table, filtered by the `memory_type` column.

| Type | Use for | Example |
|------|---------|---------|
| `episodic` | Specific events with provenance | "On run 42, the auth fix broke session cookies" |
| `semantic` | General facts about the domain | "Postgres advisory locks are session-scoped" |
| `procedural` | Reusable how-to knowledge | "When refactoring, always run mypy before pytest" |

The default is `semantic`. The `format_memories_for_prompt` helper labels
them as *Past Experience*, *Known Fact*, and *Procedure* when injecting
into a system prompt
([`src/swarm/memory/injection.py`](../src/swarm/memory/injection.py)).

### Exponential decay

Memories lose relevance over time, computed on demand:

```
relevance = 2 ^ (-days_elapsed / 30)
```

A 30-day-old memory sits at 0.5, a 60-day-old one at 0.25, and so on. The
half-life is set by `MemoryAPI.DECAY_HALF_LIFE_DAYS = 30.0` in
[`src/swarm/memory/api.py`](../src/swarm/memory/api.py).

Decay is applied lazily — calling `MemoryAPI.decay()` or `memory_prune`
recomputes scores. Stored scores are not auto-decayed on every read.

### Pruning

Memories with `relevance_score < 0.1` are eligible for pruning
(`MemoryAPI.PRUNE_THRESHOLD = 0.1`). The `memory_prune` MCP tool decays
first, then deletes anything below the threshold.

You can also prune by age via `max_age_days`.

### TF-IDF similarity

For semantic-ish recall without external dependencies, `memory_search_similar`
computes TF-IDF cosine similarity in pure Python
([`src/swarm/memory/similarity.py`](../src/swarm/memory/similarity.py)).

It is lightweight: tokenize, term-frequency, inverse-document-frequency,
cosine. Good for "find anything related to X" when the literal keywords
in X don't match. Worse than a real embedding model but free.

### FTS5 full-text search with graceful fallback

When you pass a `query` to `memory_recall`, the API uses SQLite FTS5 if
the build supports it (it almost always does). If the FTS5 extension is
unavailable, it falls back to `LIKE` substring matching transparently.
Either way, the results are ordered by `relevance_score DESC`.

User input is sanitized before the FTS5 `MATCH` expression — operators
like `*`, `^`, `NEAR`, `AND`, `OR`, `NOT` are stripped to prevent
injection.

### Automatic system-prompt injection

`format_memories_for_prompt` produces an `<agent-memory>...</agent-memory>`
block ready to append to a system prompt:

```
<agent-memory>
[Procedure] Always run mypy before pytest in this repo.
[Known Fact] The CI pipeline uses Python 3.12.
[Past Experience] Last refactor of auth.py broke OAuth callback handling.
</agent-memory>
```

It respects a `max_chars` budget (default 4000) and stops adding entries
once the budget is hit.

## MCP tool reference

Source:
[`src/swarm/mcp/memory_tools.py`](../src/swarm/mcp/memory_tools.py).
All tools accept string parameters and return JSON strings (MCP convention).

### `memory_store`

```
memory_store(agent_name, content, memory_type="semantic", context="")
```

Persist a memory. Returns the created entry as JSON.

```json
{
  "agent_name": "code-reviewer",
  "content": "Use pathlib.Path everywhere",
  "memory_type": "procedural",
  "context": "{\"step_id\": \"review\", \"plan_goal\": \"refactor auth\"}"
}
```

Response:

```json
{
  "id": "9c8d1f2a-...",
  "agent_name": "code-reviewer",
  "content": "Use pathlib.Path everywhere",
  "memory_type": "procedural",
  "context": "{\"step_id\": \"review\", ...}",
  "created_at": "2026-04-17T15:00:00+00:00"
}
```

### `memory_recall`

```
memory_recall(agent_name, memory_type="", query="", limit="20", min_relevance="0.0")
```

Returns memories ordered by relevance descending. With a `query`, uses
FTS5 (or `LIKE` fallback). Without a query, scans the agent's memories
matching the optional `memory_type` filter.

Call:

```json
{
  "agent_name": "code-reviewer",
  "query": "path handling",
  "limit": "5"
}
```

Response: JSON array of memory entries.

### `memory_search_similar`

```
memory_search_similar(agent_name, query, limit="10", min_similarity="0.1")
```

TF-IDF semantic search. Returns `[{memory, similarity_score}, ...]`.

Call:

```json
{
  "agent_name": "code-reviewer",
  "query": "filesystem operations"
}
```

Response:

```json
[
  {
    "memory": {"id": "...", "content": "Use pathlib.Path everywhere", ...},
    "similarity_score": 0.6342
  }
]
```

### `memory_reinforce`

```
memory_reinforce(memory_id, boost="0.5")
```

Adds `boost` to the memory's `relevance_score`, clamped to `[0.0, 1.0]`.
Use after a memory contributed to a successful outcome.

Call:

```json
{"memory_id": "9c8d1f2a-...", "boost": "0.3"}
```

Response: updated memory entry, or `{"error": "Memory '...' not found"}`.

### `memory_forget`

```
memory_forget(memory_id)
```

Hard-deletes a memory. Returns `{"ok": true|false, "memory_id": "..."}`.

### `memory_prune`

```
memory_prune(agent_name="", max_age_days="", min_relevance="")
```

Two-phase: applies decay first, then deletes memories matching the
condition. With no args, uses the default 0.1 threshold.

Call:

```json
{"agent_name": "code-reviewer", "max_age_days": "90"}
```

Response: `{"decayed": 42, "pruned": 3}`.

## CLI reference

There is currently **no `swarm memory` CLI subcommand**. Memory is
accessed through MCP tools from inside an orchestrator session. If you
need ad-hoc inspection, query the SQLite database directly:

```bash
sqlite3 ~/.swarm/memory.db "SELECT agent_name, memory_type, content FROM memory ORDER BY relevance_score DESC LIMIT 10;"
```

A future `swarm memory ls / inspect / prune` CLI is a reasonable
addition; tracked as a gap.

## Gotchas

- **Keyed by `agent_name`, not `agent_id`.** Agent definitions are
  immutable and cloning produces new IDs. Memory is name-scoped so a
  cloned agent inherits the parent's memory pool. If you want a
  fresh-slate clone, give it a new name.
- **FTS5 might not be present.** The build will fall back to `LIKE`
  silently. Recall still works, but ranking is by `relevance_score` only,
  not BM25.
- **Decay is per-recall, not stored.** The persisted `relevance_score`
  is the score at write/reinforce time. Calling `memory_prune` (or
  `MemoryAPI.decay()` directly) is what actually rewrites the column.
- **FTS5 query sanitization strips operators.** Don't try to pass FTS5
  syntax like `auth*` through `memory_recall` — the `*` is stripped.
  Each token is wrapped in double-quotes and joined with implicit AND.
- **Injection has a character budget.** `format_memories_for_prompt`
  stops adding entries once the cumulative size hits `max_chars`
  (default 4000). The order matters — put your most important memories
  first by sorting on `relevance_score`.
- **`memory_prune` with no arguments** falls through to the default
  0.1 relevance threshold. To prune *only* by age, pass `max_age_days`
  alone — the relevance condition will not apply.

## See also

- [`src/swarm/memory/api.py`](../src/swarm/memory/api.py) — Python API
- [`src/swarm/memory/db.py`](../src/swarm/memory/db.py) — schema and FTS5 setup
- [`src/swarm/memory/similarity.py`](../src/swarm/memory/similarity.py) — TF-IDF
- [`src/swarm/memory/injection.py`](../src/swarm/memory/injection.py) — prompt formatting
- [`src/swarm/mcp/memory_tools.py`](../src/swarm/mcp/memory_tools.py) — MCP wrappers
- [messaging.md](messaging.md) — the sibling subsystem for run-scoped agent communication
