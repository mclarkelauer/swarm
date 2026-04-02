# Design: Semantic Search (FTS5) and Agent Memory

**Status**: Draft
**Date**: 2026-04-01

---

## 1. Semantic Search (FTS5)

### 1.1 Problem

`RegistryAPI.search()` uses four LIKE clauses against name, system_prompt, description, and tags. This is O(n) per query, has no relevance ranking, and cannot match partial words or inflected forms. With 66+ agents in the catalog and growing, search quality and performance matter.

### 1.2 FTS5 Virtual Table

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS agents_fts USING fts5(
    name,
    description,
    system_prompt,
    tags,
    content='agents',
    content_rowid='rowid'
);
```

Notes:
- Uses **external content** mode (`content='agents'`) so FTS5 reads from the agents table on demand. This avoids duplicating data.
- `content_rowid='rowid'` maps the FTS5 rowid to the agents table implicit rowid.
- FTS5 indexes the four most searchable text columns. `id`, `tools`, `permissions`, and other structured fields are excluded.

### 1.3 Sync Triggers

Triggers keep the FTS5 index synchronized with the agents table on every mutation.

```sql
-- After INSERT: add the new row to the FTS index
CREATE TRIGGER IF NOT EXISTS agents_fts_insert AFTER INSERT ON agents BEGIN
    INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
    VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
END;

-- Before UPDATE: remove the old content, then re-add
CREATE TRIGGER IF NOT EXISTS agents_fts_update_delete BEFORE UPDATE ON agents BEGIN
    INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
    VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS agents_fts_update_insert AFTER UPDATE ON agents BEGIN
    INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
    VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
END;

-- After DELETE: remove from FTS index
CREATE TRIGGER IF NOT EXISTS agents_fts_delete AFTER DELETE ON agents BEGIN
    INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
    VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
END;
```

### 1.4 Initial Population

After creating the virtual table and triggers, backfill from existing data:

```sql
INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
SELECT rowid, name, description, system_prompt, tags FROM agents;
```

This is idempotent: if the FTS table already contains data, the `rebuild` command can be used instead:

```sql
INSERT INTO agents_fts(agents_fts) VALUES ('rebuild');
```

### 1.5 Migration Strategy

All FTS5 setup lives in `init_registry_db()`, guarded by a try/except so that environments without the FTS5 extension compiled in degrade gracefully.

```python
# In src/swarm/registry/db.py — init_registry_db()

def _init_fts(conn: sqlite3.Connection) -> bool:
    """Attempt to create FTS5 index. Returns True if FTS5 is available."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS agents_fts USING fts5(
                name,
                description,
                system_prompt,
                tags,
                content='agents',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS agents_fts_insert
            AFTER INSERT ON agents BEGIN
                INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
                VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_update_delete
            BEFORE UPDATE ON agents BEGIN
                INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
                VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_update_insert
            AFTER UPDATE ON agents BEGIN
                INSERT INTO agents_fts(rowid, name, description, system_prompt, tags)
                VALUES (new.rowid, new.name, new.description, new.system_prompt, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS agents_fts_delete
            AFTER DELETE ON agents BEGIN
                INSERT INTO agents_fts(agents_fts, rowid, name, description, system_prompt, tags)
                VALUES ('delete', old.rowid, old.name, old.description, old.system_prompt, old.tags);
            END;

            -- Rebuild to ensure consistency with any rows inserted before triggers existed
            INSERT INTO agents_fts(agents_fts) VALUES ('rebuild');
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        # FTS5 extension not available — fall back to LIKE search
        return False
```

The return value is stored on the connection (or the API object) so the search method knows which path to take at runtime.

### 1.6 Search Query API

FTS5 queries use `MATCH` with BM25 ranking. The API returns results sorted by relevance (best first).

```python
# In src/swarm/registry/api.py

class RegistryAPI:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = init_registry_db(db_path)
        self._fts_available = _init_fts(self._conn)

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> list[AgentDefinition]:
        """Search agents by text query.

        Uses FTS5 MATCH with BM25 ranking when available, falls back to LIKE.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.

        Returns:
            List of matching AgentDefinition objects, ordered by relevance.
        """
        if self._fts_available:
            return self._search_fts(query, limit=limit)
        return self._search_like(query)

    def _search_fts(self, query: str, *, limit: int = 50) -> list[AgentDefinition]:
        """FTS5 MATCH search with BM25 ranking."""
        # Sanitize query: escape double quotes, wrap terms for prefix matching
        sanitized = _sanitize_fts_query(query)
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM agents "
            "WHERE rowid IN ("
            "    SELECT rowid FROM agents_fts WHERE agents_fts MATCH ? "
            "    ORDER BY bm25(agents_fts) LIMIT ?"
            ")",
            (sanitized, limit),
        )
        return [self._row_to_definition(r) for r in cur.fetchall()]

    def _search_like(self, query: str) -> list[AgentDefinition]:
        """Fallback LIKE search (existing behavior)."""
        pattern = f"%{query}%"
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM agents "
            "WHERE name LIKE ? OR system_prompt LIKE ? "
            "OR description LIKE ? OR tags LIKE ?",
            (pattern, pattern, pattern, pattern),
        )
        return [self._row_to_definition(r) for r in cur.fetchall()]

    def search_with_snippets(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Search with snippet extraction for result highlighting.

        Returns dicts with agent summary fields plus a 'snippets' dict
        containing highlighted matches from each indexed column.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.

        Returns:
            List of dicts: {id, name, description, tags, rank, snippets}.
        """
        if not self._fts_available:
            # Fallback: return results without snippets
            agents = self._search_like(query)
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "tags": list(a.tags),
                    "rank": 0.0,
                    "snippets": {},
                }
                for a in agents[:limit]
            ]

        sanitized = _sanitize_fts_query(query)
        cur = self._conn.execute(
            "SELECT "
            "  a.id, a.name, a.description, a.tags, "
            "  bm25(agents_fts) AS rank, "
            "  snippet(agents_fts, 0, '<b>', '</b>', '...', 32) AS snip_name, "
            "  snippet(agents_fts, 1, '<b>', '</b>', '...', 64) AS snip_desc, "
            "  snippet(agents_fts, 2, '<b>', '</b>', '...', 64) AS snip_prompt, "
            "  snippet(agents_fts, 3, '<b>', '</b>', '...', 32) AS snip_tags "
            "FROM agents_fts "
            "JOIN agents a ON agents_fts.rowid = a.rowid "
            "WHERE agents_fts MATCH ? "
            "ORDER BY bm25(agents_fts) "
            "LIMIT ?",
            (sanitized, limit),
        )
        results: list[dict[str, object]] = []
        for row in cur.fetchall():
            snippets: dict[str, str] = {}
            if row[5]:
                snippets["name"] = row[5]
            if row[6]:
                snippets["description"] = row[6]
            if row[7]:
                snippets["system_prompt"] = row[7]
            if row[8]:
                snippets["tags"] = row[8]
            results.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "tags": json.loads(row[3]) if isinstance(row[3], str) else row[3],
                    "rank": row[4],
                    "snippets": snippets,
                }
            )
        return results
```

### 1.7 Query Sanitization

FTS5 query syntax requires care. User input must be sanitized to prevent syntax errors.

```python
def _sanitize_fts_query(query: str) -> str:
    """Convert a user query string into a safe FTS5 MATCH expression.

    - Strips FTS5 operators to prevent injection
    - Wraps each token in double-quotes for exact term matching
    - Joins tokens with implicit AND (FTS5 default)

    Examples:
        "python test"   -> '"python" "test"'
        "code-reviewer" -> '"code" "reviewer"'
        'he said "hi"'  -> '"he" "said" "hi"'
    """
    import re
    # Remove FTS5 special characters: *, ^, NEAR, AND, OR, NOT, (, ), "
    cleaned = re.sub(r'[*^"(){}]', ' ', query)
    cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', ' ', cleaned, flags=re.IGNORECASE)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    return " ".join(f'"{token}"' for token in tokens)
```

### 1.8 MCP Tool Integration

The existing `swarm_discover` and `registry_search` tools need no signature changes. They call `RegistryAPI.search()` which now transparently uses FTS5 when available.

A new MCP tool exposes snippet-based search for richer results:

```python
@mcp.tool()
def registry_search_ranked(query: str, limit: str = "20") -> str:
    """Search agents with BM25 ranking and snippet highlighting.

    Returns ranked results with highlighted snippets showing where
    the query matched in each agent's name, description, prompt, or tags.

    Args:
        query: Search terms (space-separated, implicitly ANDed).
        limit: Maximum results to return (default 20).

    Returns:
        JSON array of {id, name, description, tags, rank, snippets}.
    """
    assert state.registry_api is not None
    results = state.registry_api.search_with_snippets(
        query, limit=int(limit)
    )
    return json.dumps(results)
```

### 1.9 Example Data

Query: `"python testing"`

FTS5 MATCH expression: `'"python" "testing"'`

Result:
```json
[
  {
    "id": "a1b2c3d4-...",
    "name": "python-test-writer",
    "description": "Writes pytest test suites with high coverage",
    "tags": ["python", "testing", "pytest"],
    "rank": -2.45,
    "snippets": {
      "name": "<b>python</b>-test-writer",
      "description": "Writes pytest <b>test</b> suites with high coverage",
      "tags": "<b>python</b> <b>testing</b> pytest"
    }
  }
]
```

Note: BM25 returns negative scores (lower is better). The result set is already sorted.

---

## 2. Agent Memory System

### 2.1 Problem

Agents currently have no persistent memory. Each session starts from zero context. Agents cannot learn from past successes, failures, or user corrections. The plan system tracks execution outcomes (RunLog) but that information is not fed back into agent behavior.

### 2.2 Memory Table Schema

```sql
CREATE TABLE IF NOT EXISTS memory (
    id              TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    memory_type     TEXT NOT NULL DEFAULT 'semantic',
    content         TEXT NOT NULL,
    context         TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT '',
    relevance_score REAL NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_memory_agent_name ON memory(agent_name);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(agent_name, memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_relevance ON memory(agent_name, relevance_score DESC);
```

Column notes:
- `id` -- UUID4 as TEXT, following the `agents` table pattern.
- `agent_name` -- Keyed by name (not agent_id) because agents are immutable and cloned. The name is the stable identity across clones.
- `memory_type` -- One of `'episodic'`, `'semantic'`, `'procedural'`:
  - **episodic**: Specific events and outcomes ("In plan X, step Y failed because Z").
  - **semantic**: Factual knowledge and preferences ("User prefers ruff over flake8").
  - **procedural**: How-to knowledge and workflows ("To deploy service X, run A then B then C").
- `content` -- The memory content as free-form text.
- `context` -- JSON string with provenance metadata: step_id, plan goal, session timestamp, etc.
- `created_at` -- ISO 8601 timestamp.
- `relevance_score` -- Float in [0.0, 1.0]. Starts at 1.0, decays over time, pruned at threshold.

### 2.3 Optional FTS5 for Memory Content Search

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    content='memory',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memory BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_update_delete BEFORE UPDATE ON memory BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_update_insert AFTER UPDATE ON memory BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memory BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;
```

### 2.4 MemoryEntry Dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry for an agent.

    Memories are keyed by agent_name (not agent_id) because agent
    definitions are immutable — clones share the same name and should
    share the same memory.
    """

    id: str
    agent_name: str
    content: str
    memory_type: str = "semantic"
    context: str = ""
    created_at: str = ""
    relevance_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Sparse serialization — omit fields at their default value."""
        d: dict[str, Any] = {
            "id": self.id,
            "agent_name": self.agent_name,
            "content": self.content,
        }
        if self.memory_type != "semantic":
            d["memory_type"] = self.memory_type
        if self.context:
            d["context"] = self.context
        if self.created_at:
            d["created_at"] = self.created_at
        if self.relevance_score != 1.0:
            d["relevance_score"] = self.relevance_score
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryEntry:
        """Deserialize with backward-compatible defaults."""
        return cls(
            id=d["id"],
            agent_name=d["agent_name"],
            content=d["content"],
            memory_type=d.get("memory_type", "semantic"),
            context=d.get("context", ""),
            created_at=d.get("created_at", ""),
            relevance_score=d.get("relevance_score", 1.0),
        )
```

### 2.5 Database Initialization

A new module `src/swarm/memory/db.py` following the registry pattern:

```python
"""SQLite database initialization for the agent memory system."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path


def init_memory_db(path: Path) -> tuple[sqlite3.Connection, bool]:
    """Create (or open) the memory database and ensure schema exists.

    Args:
        path: Path to the SQLite database file.

    Returns:
        Tuple of (connection, fts_available).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id              TEXT PRIMARY KEY,
            agent_name      TEXT NOT NULL,
            memory_type     TEXT NOT NULL DEFAULT 'semantic',
            content         TEXT NOT NULL,
            context         TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT '',
            relevance_score REAL NOT NULL DEFAULT 1.0
        )
        """
    )

    # Idempotent migrations for future columns
    for col, col_type, default in [
        # Example future migration:
        # ("access_count", "INTEGER", "0"),
    ]:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                f"ALTER TABLE memory ADD COLUMN {col} {col_type} NOT NULL DEFAULT {default}"
            )

    # Indexes
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_agent_name ON memory(agent_name)"
        )
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(agent_name, memory_type)"
        )
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_relevance "
            "ON memory(agent_name, relevance_score DESC)"
        )

    conn.commit()

    # Optional FTS5 for content search
    fts_available = _init_memory_fts(conn)

    return conn, fts_available


def _init_memory_fts(conn: sqlite3.Connection) -> bool:
    """Attempt to create FTS5 index on memory content. Returns True if available."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                content='memory',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS memory_fts_insert
            AFTER INSERT ON memory BEGIN
                INSERT INTO memory_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_update_delete
            BEFORE UPDATE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_update_insert
            AFTER UPDATE ON memory BEGIN
                INSERT INTO memory_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_fts_delete
            AFTER DELETE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            INSERT INTO memory_fts(memory_fts) VALUES ('rebuild');
            """
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
```

### 2.6 MemoryAPI

```python
"""High-level Python API for the agent memory system."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

from swarm.memory.db import init_memory_db
from swarm.memory.models import MemoryEntry


class MemoryAPI:
    """CRUD operations on persistent agent memory.

    Args:
        db_path: Path to the SQLite database file.
    """

    # Memories with relevance_score below this threshold are eligible for pruning.
    PRUNE_THRESHOLD: float = 0.1

    # Half-life in days: after this many days, relevance_score is halved.
    DECAY_HALF_LIFE_DAYS: float = 30.0

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn, self._fts_available = init_memory_db(db_path)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _row_to_entry(self, row: tuple[object, ...]) -> MemoryEntry:
        return MemoryEntry(
            id=str(row[0]),
            agent_name=str(row[1]),
            memory_type=str(row[2]),
            content=str(row[3]),
            context=str(row[4]),
            created_at=str(row[5]),
            relevance_score=float(row[6]),
        )

    _SELECT_COLS = (
        "id, agent_name, memory_type, content, context, "
        "created_at, relevance_score"
    )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def store(
        self,
        agent_name: str,
        content: str,
        *,
        memory_type: str = "semantic",
        context: str = "",
    ) -> MemoryEntry:
        """Store a new memory for an agent.

        Args:
            agent_name: Agent name (stable across clones).
            content: The memory content.
            memory_type: One of 'episodic', 'semantic', 'procedural'.
            context: JSON string with provenance (step_id, plan goal, etc.).

        Returns:
            The created MemoryEntry.
        """
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            agent_name=agent_name,
            content=content,
            memory_type=memory_type,
            context=context,
            created_at=datetime.now(tz=UTC).isoformat(),
            relevance_score=1.0,
        )
        self._conn.execute(
            "INSERT INTO memory (id, agent_name, memory_type, content, "
            "context, created_at, relevance_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.agent_name,
                entry.memory_type,
                entry.content,
                entry.context,
                entry.created_at,
                entry.relevance_score,
            ),
        )
        self._conn.commit()
        return entry

    def recall(
        self,
        agent_name: str,
        *,
        memory_type: str | None = None,
        query: str | None = None,
        limit: int = 20,
        min_relevance: float = 0.0,
    ) -> list[MemoryEntry]:
        """Recall memories for an agent.

        Filters by agent_name (required), then optionally by memory_type
        and text query. Results are ordered by relevance_score descending.

        Args:
            agent_name: Agent name to recall memories for.
            memory_type: Optional filter: 'episodic', 'semantic', 'procedural'.
            query: Optional text search on content (uses FTS5 if available).
            limit: Maximum number of memories to return.
            min_relevance: Minimum relevance_score threshold.

        Returns:
            List of matching MemoryEntry objects, ordered by relevance.
        """
        if query and self._fts_available:
            return self._recall_fts(
                agent_name,
                query,
                memory_type=memory_type,
                limit=limit,
                min_relevance=min_relevance,
            )

        conditions = ["agent_name = ?"]
        params: list[object] = [agent_name]

        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)

        if min_relevance > 0.0:
            conditions.append("relevance_score >= ?")
            params.append(min_relevance)

        if query:
            # LIKE fallback
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")

        params.append(limit)
        where = " AND ".join(conditions)

        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM memory "
            f"WHERE {where} "
            "ORDER BY relevance_score DESC "
            "LIMIT ?",
            tuple(params),
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def _recall_fts(
        self,
        agent_name: str,
        query: str,
        *,
        memory_type: str | None = None,
        limit: int = 20,
        min_relevance: float = 0.0,
    ) -> list[MemoryEntry]:
        """FTS5-based memory recall."""
        from swarm.registry.api import _sanitize_fts_query

        sanitized = _sanitize_fts_query(query)

        conditions = ["m.agent_name = ?"]
        params: list[object] = [agent_name]

        if memory_type:
            conditions.append("m.memory_type = ?")
            params.append(memory_type)

        if min_relevance > 0.0:
            conditions.append("m.relevance_score >= ?")
            params.append(min_relevance)

        params.append(limit)
        where = " AND ".join(conditions)

        cur = self._conn.execute(
            f"SELECT m.id, m.agent_name, m.memory_type, m.content, "
            f"m.context, m.created_at, m.relevance_score "
            f"FROM memory m "
            f"JOIN memory_fts ON memory_fts.rowid = m.rowid "
            f"WHERE memory_fts MATCH ? AND {where} "
            f"ORDER BY bm25(memory_fts) "
            f"LIMIT ?",
            (sanitized, *params),
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def forget(self, memory_id: str) -> bool:
        """Delete a specific memory by ID.

        Args:
            memory_id: The UUID of the memory to delete.

        Returns:
            True if the memory existed and was deleted.
        """
        cur = self._conn.execute(
            "DELETE FROM memory WHERE id = ?", (memory_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def decay(self, agent_name: str | None = None) -> int:
        """Apply time-based decay to relevance scores.

        Uses exponential decay: score *= 2^(-days_elapsed / half_life).

        Args:
            agent_name: Decay only this agent's memories. None = all.

        Returns:
            Number of rows updated.
        """
        now = datetime.now(tz=UTC)
        # Fetch all eligible rows, compute new scores, batch update
        conditions = ["created_at != ''"]
        params: list[object] = []
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)

        where = " AND ".join(conditions)
        cur = self._conn.execute(
            f"SELECT id, created_at, relevance_score FROM memory WHERE {where}",
            tuple(params),
        )
        updates: list[tuple[float, str]] = []
        for row in cur.fetchall():
            memory_id = row[0]
            created_at_str = row[1]
            try:
                created_at = datetime.fromisoformat(created_at_str)
                days_elapsed = (now - created_at).total_seconds() / 86400.0
                new_score = math.pow(2.0, -days_elapsed / self.DECAY_HALF_LIFE_DAYS)
                # Clamp to [0.0, 1.0]
                new_score = max(0.0, min(1.0, new_score))
                updates.append((new_score, memory_id))
            except (ValueError, TypeError):
                continue

        if updates:
            self._conn.executemany(
                "UPDATE memory SET relevance_score = ? WHERE id = ?",
                updates,
            )
            self._conn.commit()
        return len(updates)

    def prune(
        self,
        *,
        agent_name: str | None = None,
        max_age_days: float | None = None,
        min_relevance: float | None = None,
    ) -> int:
        """Remove stale memories below the relevance threshold or older than max_age_days.

        At least one of max_age_days or min_relevance must be specified.

        Args:
            agent_name: Prune only this agent's memories. None = all.
            max_age_days: Delete memories older than this many days.
            min_relevance: Delete memories with relevance_score below this.
                Defaults to PRUNE_THRESHOLD if max_age_days is not set.

        Returns:
            Number of memories deleted.
        """
        conditions: list[str] = []
        params: list[object] = []

        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)

        pruning_conditions: list[str] = []

        if min_relevance is not None:
            pruning_conditions.append("relevance_score < ?")
            params.append(min_relevance)
        elif max_age_days is None:
            # Default to threshold
            pruning_conditions.append("relevance_score < ?")
            params.append(self.PRUNE_THRESHOLD)

        if max_age_days is not None:
            cutoff = datetime.now(tz=UTC).isoformat()
            # Use string comparison — ISO 8601 sorts correctly
            from datetime import timedelta
            cutoff_dt = datetime.now(tz=UTC) - timedelta(days=max_age_days)
            pruning_conditions.append("created_at < ?")
            params.append(cutoff_dt.isoformat())

        if not pruning_conditions:
            return 0

        # Combine: agent_name filter AND (age OR relevance condition)
        if pruning_conditions:
            conditions.append("(" + " OR ".join(pruning_conditions) + ")")

        where = " AND ".join(conditions) if conditions else "1=1"
        cur = self._conn.execute(
            f"DELETE FROM memory WHERE {where}", tuple(params)
        )
        self._conn.commit()
        return cur.rowcount
```

### 2.7 Memory Decay Formula

Relevance scores use **exponential decay** with a configurable half-life:

```
relevance_score = 2^(-days_elapsed / half_life)
```

With the default half-life of 30 days:

| Age (days) | relevance_score |
|------------|----------------|
| 0          | 1.000          |
| 7          | 0.841          |
| 15         | 0.707          |
| 30         | 0.500          |
| 60         | 0.250          |
| 90         | 0.125          |
| 120        | 0.063          |

Memories are pruned when `relevance_score < 0.1` (the `PRUNE_THRESHOLD`), which occurs at approximately 100 days with the default half-life.

Decay is not automatic. It must be triggered explicitly by calling `decay()` before `prune()`. This keeps the system deterministic and testable.

### 2.8 Memory Injection

A helper function formats recalled memories for inclusion in an agent's system prompt.

```python
def format_memories_for_prompt(
    memories: list[MemoryEntry],
    *,
    max_chars: int = 4000,
) -> str:
    """Format a list of memories as a system prompt section.

    Produces a structured text block that can be appended to an agent's
    system prompt. Respects a character budget to avoid prompt bloat.

    Args:
        memories: List of MemoryEntry objects (pre-filtered/sorted).
        max_chars: Maximum total characters for the memory block.

    Returns:
        Formatted string, or empty string if no memories.
    """
    if not memories:
        return ""

    type_labels = {
        "episodic": "Past Experience",
        "semantic": "Known Fact",
        "procedural": "Procedure",
    }

    lines: list[str] = ["<agent-memory>"]
    char_count = len(lines[0])

    for mem in memories:
        label = type_labels.get(mem.memory_type, mem.memory_type)
        entry = f"[{label}] {mem.content}"
        if char_count + len(entry) + 1 > max_chars:
            break
        lines.append(entry)
        char_count += len(entry) + 1

    lines.append("</agent-memory>")
    return "\n".join(lines)
```

### 2.9 MCP Tools

Four new MCP tools registered in `src/swarm/mcp/memory_tools.py`:

```python
"""MCP tools for agent memory."""

from __future__ import annotations

import json

from swarm.mcp import state
from swarm.mcp.instance import mcp


@mcp.tool()
def memory_store(
    agent_name: str,
    content: str,
    memory_type: str = "semantic",
    context: str = "",
) -> str:
    """Store a memory for an agent.

    Memories persist across sessions and are keyed by agent name
    (not agent ID) so that cloned agents share the same memory pool.

    Args:
        agent_name: The agent name (e.g. "code-reviewer").
        content: The memory content — what was learned.
        memory_type: One of 'episodic' (events), 'semantic' (facts),
            'procedural' (how-to). Default: 'semantic'.
        context: Optional JSON with provenance (step_id, plan goal, etc.).

    Returns:
        JSON object with the created memory entry.
    """
    assert state.memory_api is not None
    entry = state.memory_api.store(
        agent_name=agent_name,
        content=content,
        memory_type=memory_type,
        context=context,
    )
    return json.dumps(entry.to_dict())


@mcp.tool()
def memory_recall(
    agent_name: str,
    memory_type: str = "",
    query: str = "",
    limit: str = "20",
    min_relevance: str = "0.0",
) -> str:
    """Recall memories for an agent.

    Returns memories ordered by relevance score (highest first).
    Uses full-text search when a query is provided and FTS5 is available.

    Args:
        agent_name: The agent name.
        memory_type: Optional filter: 'episodic', 'semantic', 'procedural'.
        query: Optional text search on memory content.
        limit: Maximum results (default 20).
        min_relevance: Minimum relevance_score threshold (default 0.0).

    Returns:
        JSON array of memory entry objects.
    """
    assert state.memory_api is not None
    entries = state.memory_api.recall(
        agent_name=agent_name,
        memory_type=memory_type or None,
        query=query or None,
        limit=int(limit),
        min_relevance=float(min_relevance),
    )
    return json.dumps([e.to_dict() for e in entries])


@mcp.tool()
def memory_forget(memory_id: str) -> str:
    """Delete a specific memory by its ID.

    Args:
        memory_id: The UUID of the memory to delete.

    Returns:
        JSON object: {"ok": true/false, "memory_id": "..."}.
    """
    assert state.memory_api is not None
    removed = state.memory_api.forget(memory_id)
    return json.dumps({"ok": removed, "memory_id": memory_id})


@mcp.tool()
def memory_prune(
    agent_name: str = "",
    max_age_days: str = "",
    min_relevance: str = "",
) -> str:
    """Prune stale memories by age and/or relevance score.

    Applies time-based decay first, then deletes memories below the
    relevance threshold or older than max_age_days.

    Args:
        agent_name: Prune only this agent's memories. Empty = all agents.
        max_age_days: Delete memories older than this many days.
        min_relevance: Delete memories below this relevance score.
            If neither max_age_days nor min_relevance is set, uses
            the default threshold of 0.1.

    Returns:
        JSON object: {"decayed": N, "pruned": M}.
    """
    assert state.memory_api is not None
    # Apply decay first
    decayed = state.memory_api.decay(agent_name=agent_name or None)
    # Then prune
    pruned = state.memory_api.prune(
        agent_name=agent_name or None,
        max_age_days=float(max_age_days) if max_age_days else None,
        min_relevance=float(min_relevance) if min_relevance else None,
    )
    return json.dumps({"decayed": decayed, "pruned": pruned})
```

### 2.10 State Integration

Add `memory_api` to the shared MCP state module:

```python
# In src/swarm/mcp/state.py

from swarm.memory.api import MemoryAPI

registry_api: RegistryAPI | None = None
forge_api: ForgeAPI | None = None
memory_api: MemoryAPI | None = None
plans_dir: str = ""
```

Initialize in `server.main()` alongside the registry:

```python
state.memory_api = MemoryAPI(db_path=data_dir / "memory.db")
```

### 2.11 Module Layout

```
src/swarm/memory/
    __init__.py
    models.py      # MemoryEntry frozen dataclass
    db.py          # init_memory_db(), _init_memory_fts()
    api.py         # MemoryAPI class
    injection.py   # format_memories_for_prompt()
```

### 2.12 Error Class

Add to `src/swarm/errors.py`:

```python
class MemoryError(SwarmError):
    """Agent memory system errors."""
```

### 2.13 Example Data

Storing a memory:
```python
api.store(
    agent_name="code-reviewer",
    content="User's codebase uses ruff for linting, not flake8. Always suggest ruff-compatible fixes.",
    memory_type="semantic",
    context='{"step_id": "review-1", "plan_goal": "Review auth module"}',
)
```

Stored entry (sparse serialized):
```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "agent_name": "code-reviewer",
  "content": "User's codebase uses ruff for linting, not flake8. Always suggest ruff-compatible fixes.",
  "context": "{\"step_id\": \"review-1\", \"plan_goal\": \"Review auth module\"}"
}
```

Note: `memory_type` is omitted because it equals the default `"semantic"`. `relevance_score` is omitted because it equals the default `1.0`. This follows the sparse serialization pattern from `PlanStep.to_dict()`.

Recalling memories:
```python
memories = api.recall("code-reviewer", memory_type="semantic", limit=5)
```

Formatted for prompt injection:
```
<agent-memory>
[Known Fact] User's codebase uses ruff for linting, not flake8. Always suggest ruff-compatible fixes.
[Past Experience] In plan "Review auth module", the review was rejected because it suggested print() for debugging instead of structlog.
[Procedure] To run tests in this codebase: uv run pytest tests/ -v --tb=short
</agent-memory>
```

Pruning after decay:
```python
decayed = api.decay("code-reviewer")      # Update scores based on age
pruned = api.prune(min_relevance=0.1)     # Remove memories below 0.1
```

---

## 3. Implementation Checklist

### Semantic Search (FTS5)
- [ ] Add `_init_fts()` to `src/swarm/registry/db.py`
- [ ] Store `_fts_available` flag on `RegistryAPI`
- [ ] Add `_sanitize_fts_query()` helper
- [ ] Split `search()` into `_search_fts()` and `_search_like()`
- [ ] Add `search_with_snippets()` method
- [ ] Add `registry_search_ranked` MCP tool
- [ ] Tests: FTS5 search, BM25 ordering, snippet extraction, LIKE fallback, query sanitization
- [ ] Update tool count in CLAUDE.md (31 -> 32)

### Agent Memory
- [ ] Create `src/swarm/memory/__init__.py`
- [ ] Create `src/swarm/memory/models.py` with `MemoryEntry`
- [ ] Create `src/swarm/memory/db.py` with `init_memory_db()`
- [ ] Create `src/swarm/memory/api.py` with `MemoryAPI`
- [ ] Create `src/swarm/memory/injection.py` with `format_memories_for_prompt()`
- [ ] Add `MemoryError` to `src/swarm/errors.py`
- [ ] Create `src/swarm/mcp/memory_tools.py` with 4 MCP tools
- [ ] Add `memory_api` to `src/swarm/mcp/state.py`
- [ ] Initialize `MemoryAPI` in `src/swarm/mcp/server.py`
- [ ] Tests: store, recall, recall with FTS, forget, decay, prune, injection formatting, MCP tools
- [ ] Update tool count in CLAUDE.md (32 -> 36)
