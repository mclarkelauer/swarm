"""High-level Python API for the agent registry."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from swarm.errors import RegistryError
from swarm.registry.db import init_registry_db
from swarm.registry.models import AgentDefinition


def _sanitize_fts_query(query: str) -> str:
    """Convert a user query string into a safe FTS5 MATCH expression.

    - Strips FTS5 operators to prevent injection
    - Wraps each token in double-quotes with a trailing ``*`` for prefix
      matching so that ``review`` matches ``reviewer``
    - Joins tokens with implicit AND (FTS5 default)

    Examples:
        "python test"   -> '"python"* "test"*'
        "code-reviewer" -> '"code"* "reviewer"*'
        'he said "hi"'  -> '"he"* "said"* "hi"*'
    """
    # Remove FTS5 special characters: *, ^, NEAR, AND, OR, NOT, (, ), "
    cleaned = re.sub(r'[*^"(){}]', ' ', query)
    cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', ' ', cleaned, flags=re.IGNORECASE)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    return " ".join(f'"{token}"*' for token in tokens)


class RegistryAPI:
    """CRUD operations on the persistent agent registry.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn, self._fts_available = init_registry_db(db_path)

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
        )

    _SELECT_COLS = (
        "id, name, parent_id, system_prompt, tools, permissions, "
        "working_dir, source, created_at, description, tags, "
        "usage_count, failure_count, last_used, notes, status"
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
        )

        self._conn.execute(
            "INSERT INTO agents (id, name, parent_id, system_prompt, tools, "
            "permissions, working_dir, source, created_at, description, tags, "
            "usage_count, failure_count, last_used, notes, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def clone(self, agent_id: str, overrides: dict[str, str | int | list[str]]) -> AgentDefinition:
        """Clone an existing definition with overrides. Sets ``parent_id``.

        Performance counter overrides (``usage_count``, ``failure_count``,
        ``last_used``) are respected when present.  All other counters default
        to zero / empty so that fresh clones start clean.
        """
        original = self.get(agent_id)
        if original is None:
            raise RegistryError(f"Cannot clone: agent '{agent_id}' not found")

        data = original.to_dict()
        data.update(overrides)

        new_id = str(uuid.uuid4())
        created_at = datetime.now(tz=UTC).isoformat()

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
            status="active",
        )

        self._conn.execute(
            "INSERT INTO agents (id, name, parent_id, system_prompt, tools, "
            "permissions, working_dir, source, created_at, description, tags, "
            "usage_count, failure_count, last_used, notes, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
