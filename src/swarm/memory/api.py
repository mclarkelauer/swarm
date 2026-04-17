"""High-level Python API for the agent memory system."""

from __future__ import annotations

import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from swarm.memory.db import init_memory_db
from swarm.memory.models import MemoryEntry


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
    # Remove FTS5 special characters: *, ^, NEAR, AND, OR, NOT, (, ), "
    cleaned = re.sub(r'[*^"(){}]', " ", query)
    cleaned = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", cleaned, flags=re.IGNORECASE)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    return " ".join(f'"{token}"' for token in tokens)


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
            relevance_score=float(row[6]),  # type: ignore[arg-type]
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
            "SELECT m.id, m.agent_name, m.memory_type, m.content, "
            "m.context, m.created_at, m.relevance_score "
            "FROM memory m "
            "JOIN memory_fts ON memory_fts.rowid = m.rowid "
            f"WHERE memory_fts MATCH ? AND {where} "
            "ORDER BY bm25(memory_fts) "
            "LIMIT ?",
            (sanitized, *params),
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def recall_similar(
        self,
        agent_name: str,
        query: str,
        *,
        limit: int = 10,
        min_relevance: float = 0.0,
        min_similarity: float = 0.1,
    ) -> list[tuple[MemoryEntry, float]]:
        """Recall memories using TF-IDF similarity search.

        Provides semantic similarity ranking without external dependencies.
        Falls back to keyword search if the similarity module is unavailable.

        Args:
            agent_name: Agent name to recall memories for.
            query: Search query text.
            limit: Maximum number of memories to return.
            min_relevance: Minimum relevance_score threshold.
            min_similarity: Minimum similarity score threshold (0.0-1.0).

        Returns:
            List of (MemoryEntry, similarity_score) tuples, ordered by
            similarity descending.
        """
        from swarm.memory.similarity import similarity_search

        # Fetch all candidate memories for this agent
        conditions = ["agent_name = ?"]
        params: list[object] = [agent_name]
        if min_relevance > 0.0:
            conditions.append("relevance_score >= ?")
            params.append(min_relevance)

        where = " AND ".join(conditions)
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM memory WHERE {where} "
            "ORDER BY relevance_score DESC",
            tuple(params),
        )
        entries = [self._row_to_entry(r) for r in cur.fetchall()]
        if not entries:
            return []

        # Run similarity search
        documents = [e.content for e in entries]
        scored = similarity_search(
            query, documents, top_k=limit, min_score=min_similarity,
        )

        return [(entries[idx], score) for idx, score in scored]

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

    def reinforce(
        self,
        memory_id: str,
        boost: float = 0.5,
    ) -> MemoryEntry | None:
        """Boost a memory's relevance score.

        Reinforces a memory that proved useful, counteracting time-based
        decay.  The new score is clamped to [0.0, 1.0].

        Args:
            memory_id: The UUID of the memory to reinforce.
            boost: Amount to add to relevance_score (default 0.5).

        Returns:
            The updated MemoryEntry, or None if not found.
        """
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM memory WHERE id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        entry = self._row_to_entry(row)
        new_score = min(1.0, max(0.0, entry.relevance_score + boost))

        self._conn.execute(
            "UPDATE memory SET relevance_score = ? WHERE id = ?",
            (new_score, memory_id),
        )
        self._conn.commit()

        return MemoryEntry(
            id=entry.id,
            agent_name=entry.agent_name,
            content=entry.content,
            memory_type=entry.memory_type,
            context=entry.context,
            created_at=entry.created_at,
            relevance_score=new_score,
        )

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

        At least one of max_age_days or min_relevance must be specified,
        otherwise the default ``PRUNE_THRESHOLD`` is applied.

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
            cutoff_dt = datetime.now(tz=UTC) - timedelta(days=max_age_days)
            pruning_conditions.append("created_at < ?")
            params.append(cutoff_dt.isoformat())

        if not pruning_conditions:
            return 0

        # Combine: agent_name filter AND (age OR relevance condition)
        conditions.append("(" + " OR ".join(pruning_conditions) + ")")

        where = " AND ".join(conditions) if conditions else "1=1"
        cur = self._conn.execute(
            f"DELETE FROM memory WHERE {where}", tuple(params)
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> MemoryAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
