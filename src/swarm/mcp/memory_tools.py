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
        content: The memory content -- what was learned.
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
def memory_reinforce(
    memory_id: str,
    boost: str = "0.5",
) -> str:
    """Boost a memory's relevance score when it proves useful.

    Counteracts time-based decay by adding to the relevance score.
    Use this when an agent's recalled memory contributed to a
    successful outcome.

    Args:
        memory_id: The UUID of the memory to reinforce.
        boost: Amount to add to relevance_score (default 0.5).
            Clamped to [0.0, 1.0].

    Returns:
        JSON object with the updated memory entry, or error if not found.
    """
    assert state.memory_api is not None
    entry = state.memory_api.reinforce(memory_id, boost=float(boost))
    if entry is None:
        return json.dumps({"error": f"Memory '{memory_id}' not found"})
    return json.dumps(entry.to_dict())


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


@mcp.tool()
def memory_search_similar(
    agent_name: str,
    query: str,
    limit: str = "10",
    min_similarity: str = "0.1",
) -> str:
    """Search memories using TF-IDF semantic similarity.

    Goes beyond keyword matching to find semantically related memories.
    Uses lightweight TF-IDF cosine similarity (no external dependencies).

    Args:
        agent_name: The agent name.
        query: Natural language search query.
        limit: Maximum results (default 10).
        min_similarity: Minimum similarity score 0.0-1.0 (default 0.1).

    Returns:
        JSON array of {memory, similarity_score} objects.
    """
    assert state.memory_api is not None
    results = state.memory_api.recall_similar(
        agent_name=agent_name,
        query=query,
        limit=int(limit),
        min_similarity=float(min_similarity),
    )
    return json.dumps([
        {"memory": e.to_dict(), "similarity_score": round(score, 4)}
        for e, score in results
    ])
