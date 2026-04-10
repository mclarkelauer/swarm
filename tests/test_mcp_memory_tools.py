"""Tests for swarm.mcp.memory_tools: memory_store, memory_recall, memory_forget, memory_prune."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swarm.memory.api import MemoryAPI
from swarm.mcp import state
from swarm.mcp.memory_tools import (
    memory_forget,
    memory_prune,
    memory_recall,
    memory_reinforce,
    memory_store,
)


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> None:
    state.memory_api = MemoryAPI(tmp_path / "memory.db")


class TestMemoryStore:
    def test_memory_store_returns_entry(self) -> None:
        result = json.loads(memory_store("agent-a", "Learned something."))
        assert result["agent_name"] == "agent-a"
        assert result["content"] == "Learned something."
        assert "id" in result

    def test_memory_store_with_type_and_context(self) -> None:
        result = json.loads(
            memory_store(
                "agent-a",
                "Deployment failed.",
                memory_type="episodic",
                context='{"step_id": "s1"}',
            )
        )
        assert result["memory_type"] == "episodic"
        assert result["context"] == '{"step_id": "s1"}'

    def test_memory_store_default_type_omitted_in_sparse_dict(self) -> None:
        result = json.loads(memory_store("agent-a", "A fact."))
        # Sparse serialization: default "semantic" type is omitted
        assert "memory_type" not in result


class TestMemoryRecall:
    def test_memory_recall_returns_stored_entries(self) -> None:
        memory_store("agent-a", "Fact one.")
        memory_store("agent-a", "Fact two.")
        result = json.loads(memory_recall("agent-a"))
        assert len(result) == 2

    def test_memory_recall_filters_by_type(self) -> None:
        memory_store("agent-a", "A fact.", memory_type="semantic")
        memory_store("agent-a", "An event.", memory_type="episodic")
        result = json.loads(memory_recall("agent-a", memory_type="episodic"))
        assert len(result) == 1
        assert result[0]["memory_type"] == "episodic"

    def test_memory_recall_filters_by_query(self) -> None:
        memory_store("agent-a", "Python is great for scripting.")
        memory_store("agent-a", "Rust is great for performance.")
        result = json.loads(memory_recall("agent-a", query="Python"))
        assert len(result) == 1
        assert "Python" in result[0]["content"]

    def test_memory_recall_empty_for_unknown_agent(self) -> None:
        result = json.loads(memory_recall("nonexistent"))
        assert result == []

    def test_memory_recall_respects_limit(self) -> None:
        for i in range(10):
            memory_store("agent-a", f"Memory {i}.")
        result = json.loads(memory_recall("agent-a", limit="3"))
        assert len(result) == 3


class TestMemoryForget:
    def test_memory_forget_removes_entry(self) -> None:
        stored = json.loads(memory_store("agent-a", "To forget."))
        result = json.loads(memory_forget(stored["id"]))
        assert result["ok"] is True
        assert result["memory_id"] == stored["id"]
        # Verify it's gone
        recalled = json.loads(memory_recall("agent-a"))
        assert len(recalled) == 0

    def test_memory_forget_nonexistent_returns_false(self) -> None:
        result = json.loads(memory_forget("nonexistent-id"))
        assert result["ok"] is False
        assert result["memory_id"] == "nonexistent-id"


class TestMemoryPrune:
    def test_memory_prune_decays_and_prunes(self) -> None:
        stored = json.loads(memory_store("agent-a", "Old memory."))
        # Make the memory very old so decay brings it below threshold
        assert state.memory_api is not None
        old_ts = (datetime.now(tz=UTC) - timedelta(days=365)).isoformat()
        state.memory_api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?",
            (old_ts, stored["id"]),
        )
        state.memory_api._conn.commit()

        result = json.loads(memory_prune("agent-a"))
        assert result["decayed"] >= 1
        assert result["pruned"] >= 1

    def test_memory_prune_with_max_age(self) -> None:
        stored = json.loads(memory_store("agent-a", "Ancient memory."))
        assert state.memory_api is not None
        old_ts = (datetime.now(tz=UTC) - timedelta(days=100)).isoformat()
        state.memory_api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?",
            (old_ts, stored["id"]),
        )
        state.memory_api._conn.commit()

        result = json.loads(memory_prune("agent-a", max_age_days="30"))
        assert result["pruned"] >= 1

    def test_memory_prune_all_agents(self) -> None:
        s1 = json.loads(memory_store("agent-a", "Old A."))
        s2 = json.loads(memory_store("agent-b", "Old B."))
        assert state.memory_api is not None
        old_ts = (datetime.now(tz=UTC) - timedelta(days=365)).isoformat()
        for sid in [s1["id"], s2["id"]]:
            state.memory_api._conn.execute(
                "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, sid)
            )
        state.memory_api._conn.commit()

        # Prune all agents (empty string agent_name)
        result = json.loads(memory_prune())
        assert result["decayed"] >= 2

    def test_memory_prune_with_min_relevance(self) -> None:
        stored = json.loads(memory_store("agent-a", "Low relevance."))
        assert state.memory_api is not None
        # Set relevance low AND remove timestamp so decay() won't reset the score
        state.memory_api._conn.execute(
            "UPDATE memory SET relevance_score = 0.05, created_at = '' WHERE id = ?",
            (stored["id"],),
        )
        state.memory_api._conn.commit()

        result = json.loads(memory_prune("agent-a", min_relevance="0.5"))
        assert result["pruned"] >= 1

    def test_memory_prune_no_entries_returns_zeros(self) -> None:
        result = json.loads(memory_prune("nonexistent-agent"))
        assert result["decayed"] == 0
        assert result["pruned"] == 0


class TestMemoryReinforce:
    def test_memory_reinforce_boosts_score(self) -> None:
        stored = json.loads(memory_store("agent-x", "useful fact"))
        memory_id = stored["id"]

        # Set relevance low first
        assert state.memory_api is not None
        state.memory_api._conn.execute(
            "UPDATE memory SET relevance_score = 0.3 WHERE id = ?",
            (memory_id,),
        )
        state.memory_api._conn.commit()

        result = json.loads(memory_reinforce(memory_id, boost="0.5"))
        assert "error" not in result
        assert result["relevance_score"] == pytest.approx(0.8)

    def test_memory_reinforce_clamps_at_one(self) -> None:
        stored = json.loads(memory_store("agent-x", "another fact"))
        memory_id = stored["id"]

        result = json.loads(memory_reinforce(memory_id, boost="0.3"))
        # relevance_score=1.0 is the default, so sparse serialization may omit it
        assert result.get("relevance_score", 1.0) == 1.0

    def test_memory_reinforce_default_boost(self) -> None:
        stored = json.loads(memory_store("agent-x", "third fact"))
        memory_id = stored["id"]

        assert state.memory_api is not None
        state.memory_api._conn.execute(
            "UPDATE memory SET relevance_score = 0.4 WHERE id = ?",
            (memory_id,),
        )
        state.memory_api._conn.commit()

        result = json.loads(memory_reinforce(memory_id))
        assert result["relevance_score"] == pytest.approx(0.9)

    def test_memory_reinforce_not_found(self) -> None:
        result = json.loads(memory_reinforce("nonexistent-id"))
        assert "error" in result
