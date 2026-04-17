"""High-level Python API for the agent registry."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from swarm._db_pool import ThreadLocalConnectionPool
from swarm._fts import sanitize_fts_query
from swarm.errors import RegistryError
from swarm.registry.db import init_registry_schema
from swarm.registry.models import AgentDefinition


def _sanitize_fts_query(query: str) -> str:
    """Backwards-compatible wrapper around :func:`swarm._fts.sanitize_fts_query`.

    Preserves the historical prefix-matching semantics (``"review"*``)
    used by the agent registry so existing imports keep working.
    """
    return sanitize_fts_query(query, prefix=True)


class RegistryAPI:
    """CRUD operations on the persistent agent registry.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        # FTS5 availability is detected once on the first connection
        # (cached on the pool initializer), then reused across threads.
        self._fts_available: bool = False

        def _init(conn: sqlite3.Connection) -> None:
            available = init_registry_schema(conn)
            # Cache the first observation; FTS availability cannot
            # change between connections to the same SQLite build.
            self._fts_available = self._fts_available or available

        self._pool: ThreadLocalConnectionPool = ThreadLocalConnectionPool(
            db_path, initializer=_init,
        )
        # Touch the pool to force schema creation and FTS detection now
        # rather than lazily on the first query.
        self._pool.get()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the SQLite connection bound to the calling thread."""
        return self._pool.get()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Backwards-compatible alias for :meth:`_get_conn`.

        Older call sites (catalog seeding, tests) read ``api._conn``
        directly.  Routing through the thread-local pool keeps those
        sites thread-safe without API changes.
        """
        return self._pool.get()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _row_to_definition(self, row: tuple[str, ...]) -> AgentDefinition:
        return AgentDefinition(
            id=row[0],
            name=row[1],
            parent_id=row[2],
            system_prompt=row[3],
            tools=tuple(json.loads(row[4])),
            permissions=tuple(json.loads(row[5])),
            working_dir=row[6],
            source=row[7],
            created_at=row[8],
            description=row[9],
            tags=tuple(json.loads(row[10])),
            usage_count=int(row[11]),
            failure_count=int(row[12]),
            last_used=row[13],
            notes=row[14],
            status=row[15],
            version=int(row[16]),
        )

    _SELECT_COLS = (
        "id, name, parent_id, system_prompt, tools, permissions, "
        "working_dir, source, created_at, description, tags, "
        "usage_count, failure_count, last_used, notes, status, version"
    )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        system_prompt: str,
        tools: list[str],
        permissions: list[str],
        working_dir: str = "",
        source: str = "forge",
        description: str = "",
        tags: list[str] | None = None,
        notes: str = "",
        status: str = "active",
        version: int = 1,
    ) -> AgentDefinition:
        """Register a new agent definition."""
        agent_id = str(uuid.uuid4())
        created_at = datetime.now(tz=UTC).isoformat()
        resolved_tags: list[str] = tags if tags is not None else []

        defn = AgentDefinition(
            id=agent_id,
            name=name,
            system_prompt=system_prompt,
            tools=tuple(tools),
            permissions=tuple(permissions),
            working_dir=working_dir,
            description=description,
            tags=tuple(resolved_tags),
            source=source,
            created_at=created_at,
            notes=notes,
            status=status,
            version=version,
        )

        self._conn.execute(
            "INSERT INTO agents (id, name, parent_id, system_prompt, tools, "
            "permissions, working_dir, source, created_at, description, tags, "
            "usage_count, failure_count, last_used, notes, status, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                defn.id,
                defn.name,
                defn.parent_id,
                defn.system_prompt,
                json.dumps(list(defn.tools)),
                json.dumps(list(defn.permissions)),
                defn.working_dir,
                defn.source,
                defn.created_at,
                defn.description,
                json.dumps(list(defn.tags)),
                defn.usage_count,
                defn.failure_count,
                defn.last_used,
                defn.notes,
                defn.status,
                defn.version,
            ),
        )
        self._conn.commit()
        return defn

    def get(self, agent_id: str) -> AgentDefinition | None:
        """Retrieve a single agent definition by ID, or ``None``."""
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM agents WHERE id = ?",
            (agent_id,),
        )
        row = cur.fetchone()
        return self._row_to_definition(row) if row else None

    def list_agents(self, name_filter: str | None = None) -> list[AgentDefinition]:
        """List agent definitions, optionally filtering by name substring."""
        if name_filter:
            cur = self._conn.execute(
                f"SELECT {self._SELECT_COLS} FROM agents WHERE name LIKE ?",
                (f"%{name_filter}%",),
            )
        else:
            cur = self._conn.execute(f"SELECT {self._SELECT_COLS} FROM agents")
        return [self._row_to_definition(r) for r in cur.fetchall()]

    def search(
        self,
        query: str,
        *,
        limit: int = 200,
    ) -> list[AgentDefinition]:
        """Search agents by text query.

        Uses FTS5 MATCH with BM25 ranking when available, falls back to LIKE.

        Args:
            query: The search query string.
            limit: Maximum number of results to return (default 200).

        Returns:
            List of matching AgentDefinition objects, ordered by relevance.
        """
        if self._fts_available:
            return self._search_fts(query, limit=limit)
        return self._search_like(query)

    def _search_fts(self, query: str, *, limit: int = 200) -> list[AgentDefinition]:
        """FTS5 MATCH search with BM25 ranking."""
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

    def update(self, agent_id: str, updates: dict[str, str | int | list[str]]) -> AgentDefinition | None:
        """Update fields on an existing agent definition in-place.

        Only allows updating non-structural fields: description, tags, notes,
        status, working_dir.  Structural changes (system_prompt, tools,
        permissions) require cloning.

        Args:
            agent_id: ID of the agent to update.
            updates: Dict of field->value pairs to update.

        Returns:
            The updated AgentDefinition, or None if not found.
        """
        allowed_fields = {"description", "tags", "notes", "status", "working_dir"}
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            return self.get(agent_id)

        set_clauses = []
        params: list[object] = []
        for key, value in filtered.items():
            if key == "tags" and isinstance(value, list):
                set_clauses.append(f"{key} = ?")
                params.append(json.dumps(value))
            else:
                set_clauses.append(f"{key} = ?")
                params.append(str(value) if not isinstance(value, int) else value)

        params.append(agent_id)
        self._conn.execute(
            f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = ?",
            tuple(params),
        )
        self._conn.commit()
        return self.get(agent_id)

    def clone(self, agent_id: str, overrides: dict[str, str | int | list[str]]) -> AgentDefinition:
        """Clone an existing definition with overrides. Sets ``parent_id``.

        Performance counter overrides (``usage_count``, ``failure_count``,
        ``last_used``) are respected when present.  All other counters default
        to zero / empty so that fresh clones start clean.

        The ``version`` field auto-increments from the original unless
        explicitly overridden.
        """
        original = self.get(agent_id)
        if original is None:
            raise RegistryError(f"Cannot clone: agent '{agent_id}' not found")

        data = original.to_dict()
        data.update(overrides)

        new_id = str(uuid.uuid4())
        created_at = datetime.now(tz=UTC).isoformat()

        # Auto-increment version from original unless explicitly overridden
        version = int(overrides["version"]) if "version" in overrides else original.version + 1  # type: ignore[arg-type]

        defn = AgentDefinition(
            id=new_id,
            name=data["name"],
            parent_id=agent_id,
            system_prompt=data["system_prompt"],
            tools=tuple(data.get("tools", list(original.tools))),
            permissions=tuple(data.get("permissions", list(original.permissions))),
            working_dir=data.get("working_dir", original.working_dir),
            description=data.get("description", original.description),
            tags=tuple(data.get("tags", list(original.tags))),
            source=original.source,
            created_at=created_at,
            # Performance counters: use explicit override value when provided,
            # otherwise start fresh at 0/"" (standard clone behaviour).
            usage_count=int(overrides["usage_count"]) if "usage_count" in overrides else 0,  # type: ignore[arg-type]
            failure_count=int(overrides["failure_count"]) if "failure_count" in overrides else 0,  # type: ignore[arg-type]
            last_used=str(overrides["last_used"]) if "last_used" in overrides else "",
            notes=data.get("notes", original.notes),
            # Status defaults to "active" on clone but honours an explicit override.
            status=str(overrides["status"]) if "status" in overrides else "active",
            version=version,
        )

        self._conn.execute(
            "INSERT INTO agents (id, name, parent_id, system_prompt, tools, "
            "permissions, working_dir, source, created_at, description, tags, "
            "usage_count, failure_count, last_used, notes, status, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                defn.id,
                defn.name,
                defn.parent_id,
                defn.system_prompt,
                json.dumps(list(defn.tools)),
                json.dumps(list(defn.permissions)),
                defn.working_dir,
                defn.source,
                defn.created_at,
                defn.description,
                json.dumps(list(defn.tags)),
                defn.usage_count,
                defn.failure_count,
                defn.last_used,
                defn.notes,
                defn.status,
                defn.version,
            ),
        )
        self._conn.commit()
        return defn

    def remove(self, agent_id: str) -> bool:
        """Remove an agent definition. Returns ``True`` if it existed."""
        cur = self._conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def resolve_agent(self, identifier: str) -> AgentDefinition:
        """Resolve an agent by ID or exact name.

        Tries ``get(identifier)`` first (UUID lookup).  On miss, falls
        back to ``list_agents(name_filter=identifier)`` and picks the
        exact match.  If there is exactly one result, returns it even
        without an exact name match (convenience for unambiguous substrings).

        Raises:
            RegistryError: If the identifier cannot be resolved to
                exactly one agent.
        """
        defn = self.get(identifier)
        if defn is not None:
            return defn

        candidates = self.list_agents(name_filter=identifier)
        # Exact name match wins
        for c in candidates:
            if c.name == identifier:
                return c
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise RegistryError(f"Agent '{identifier}' not found")
        names = ", ".join(c.name for c in candidates)
        raise RegistryError(
            f"Ambiguous identifier '{identifier}': matches {names}. Use the full ID."
        )

    def record_metric(
        self,
        agent_name: str,
        *,
        success: bool = True,
        duration_seconds: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> dict[str, object]:
        """Record a metric data point for an agent.

        Accumulates across runs. Also increments usage_count/failure_count
        on the agent definition.

        Args:
            agent_name: The agent name (stable across clones).
            success: Whether the run was successful.
            duration_seconds: How long the step took.
            tokens_used: Tokens consumed.
            cost_usd: Cost in USD.

        Returns:
            Dict with updated metrics.
        """
        now = datetime.now(tz=UTC).isoformat()

        # Upsert into agent_metrics
        self._conn.execute(
            """
            INSERT INTO agent_metrics (agent_name, total_runs, total_successes,
                total_failures, total_tokens, total_cost_usd, avg_duration_seconds,
                last_run_at, updated_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_name) DO UPDATE SET
                total_runs = total_runs + 1,
                total_successes = total_successes + ?,
                total_failures = total_failures + ?,
                total_tokens = total_tokens + ?,
                total_cost_usd = total_cost_usd + ?,
                avg_duration_seconds = (avg_duration_seconds * total_runs + ?) / (total_runs + 1),
                last_run_at = ?,
                updated_at = ?
            """,
            (
                agent_name,
                1 if success else 0,
                0 if success else 1,
                tokens_used,
                cost_usd,
                duration_seconds,
                now,
                now,
                # ON CONFLICT params
                1 if success else 0,
                0 if success else 1,
                tokens_used,
                cost_usd,
                duration_seconds,
                now,
                now,
            ),
        )
        self._conn.commit()

        return self.get_metrics(agent_name) or {}

    def get_metrics(self, agent_name: str) -> dict[str, object] | None:
        """Get accumulated metrics for an agent.

        Args:
            agent_name: The agent name.

        Returns:
            Dict with metrics, or None if no data.
        """
        cur = self._conn.execute(
            "SELECT agent_name, total_runs, total_successes, total_failures, "
            "total_tokens, total_cost_usd, avg_duration_seconds, last_run_at, "
            "updated_at FROM agent_metrics WHERE agent_name = ?",
            (agent_name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "agent_name": row[0],
            "total_runs": row[1],
            "total_successes": row[2],
            "total_failures": row[3],
            "total_tokens": row[4],
            "total_cost_usd": row[5],
            "avg_duration_seconds": row[6],
            "last_run_at": row[7],
            "updated_at": row[8],
            "success_rate": row[2] / row[1] if row[1] > 0 else 1.0,
        }

    def list_metrics(self) -> list[dict[str, object]]:
        """List metrics for all agents, ordered by total_runs descending.

        Returns:
            List of metric dicts.
        """
        cur = self._conn.execute(
            "SELECT agent_name, total_runs, total_successes, total_failures, "
            "total_tokens, total_cost_usd, avg_duration_seconds, last_run_at, "
            "updated_at FROM agent_metrics ORDER BY total_runs DESC"
        )
        results: list[dict[str, object]] = []
        for row in cur.fetchall():
            results.append({
                "agent_name": row[0],
                "total_runs": row[1],
                "total_successes": row[2],
                "total_failures": row[3],
                "total_tokens": row[4],
                "total_cost_usd": row[5],
                "avg_duration_seconds": row[6],
                "last_run_at": row[7],
                "updated_at": row[8],
                "success_rate": row[2] / row[1] if row[1] > 0 else 1.0,
            })
        return results

    def inspect(self, agent_id: str) -> dict[str, object]:
        """Return full detail including the provenance chain."""
        defn = self.get(agent_id)
        if defn is None:
            raise RegistryError(f"Agent '{agent_id}' not found")

        result = defn.to_dict()

        # Walk provenance chain
        chain: list[dict[str, str]] = []
        current = defn
        while current.parent_id:
            parent = self.get(current.parent_id)
            if parent is None:
                break
            chain.append({"id": parent.id, "name": parent.name})
            current = parent

        result["provenance_chain"] = chain
        return result

    def count(self) -> int:
        """Return the total number of agent definitions stored.

        Public alternative to ``len(api.list_agents())`` that avoids
        materializing every row.
        """
        cur = self._get_conn().execute("SELECT COUNT(*) FROM agents")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close every thread-local SQLite connection."""
        self._pool.close_all()

    def __enter__(self) -> RegistryAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
