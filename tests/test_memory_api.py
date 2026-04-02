"""Tests for swarm.memory.api: MemoryAPI."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swarm.memory.api import MemoryAPI
from swarm.memory.models import MemoryEntry


@pytest.fixture()
def api(tmp_path: Path) -> MemoryAPI:
    return MemoryAPI(tmp_path / "memory.db")


class TestStore:
    def test_store_creates_entry(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Some fact.")
        assert isinstance(entry, MemoryEntry)
        assert entry.agent_name == "agent-a"
        assert entry.content == "Some fact."

    def test_store_sets_uuid_and_timestamp(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Something learned.")
        # id should be a valid UUID4
        parsed = uuid.UUID(entry.id, version=4)
        assert str(parsed) == entry.id
        # created_at should be a parseable ISO timestamp
        dt = datetime.fromisoformat(entry.created_at)
        assert dt.tzinfo is not None

    def test_store_default_memory_type_is_semantic(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "A fact.")
        assert entry.memory_type == "semantic"

    def test_store_custom_memory_type(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Event happened.", memory_type="episodic")
        assert entry.memory_type == "episodic"

    def test_store_with_context(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Learned.", context='{"step_id": "s1"}')
        assert entry.context == '{"step_id": "s1"}'

    def test_store_initial_relevance_is_one(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Fact.")
        assert entry.relevance_score == 1.0


class TestRecall:
    def test_recall_by_agent_name(self, api: MemoryAPI) -> None:
        api.store("agent-a", "Memory for A.")
        api.store("agent-b", "Memory for B.")
        results = api.recall("agent-a")
        assert len(results) == 1
        assert results[0].agent_name == "agent-a"
        assert results[0].content == "Memory for A."

    def test_recall_filters_by_memory_type(self, api: MemoryAPI) -> None:
        api.store("agent-a", "Fact 1.", memory_type="semantic")
        api.store("agent-a", "Event 1.", memory_type="episodic")
        api.store("agent-a", "Procedure 1.", memory_type="procedural")
        results = api.recall("agent-a", memory_type="episodic")
        assert len(results) == 1
        assert results[0].memory_type == "episodic"

    def test_recall_filters_by_query_text(self, api: MemoryAPI) -> None:
        api.store("agent-a", "Python is great for scripting.")
        api.store("agent-a", "Rust is great for performance.")
        # Force LIKE fallback by disabling FTS
        api._fts_available = False
        results = api.recall("agent-a", query="Python")
        assert len(results) == 1
        assert "Python" in results[0].content

    def test_recall_respects_limit(self, api: MemoryAPI) -> None:
        for i in range(10):
            api.store("agent-a", f"Memory number {i}.")
        results = api.recall("agent-a", limit=3)
        assert len(results) == 3

    def test_recall_respects_min_relevance(self, api: MemoryAPI) -> None:
        e1 = api.store("agent-a", "High relevance.")
        e2 = api.store("agent-a", "Low relevance.")
        # Manually lower one entry's relevance
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.05 WHERE id = ?", (e2.id,)
        )
        api._conn.commit()
        results = api.recall("agent-a", min_relevance=0.5)
        assert len(results) == 1
        assert results[0].id == e1.id

    def test_recall_ordered_by_relevance_descending(self, api: MemoryAPI) -> None:
        e1 = api.store("agent-a", "Low.")
        e2 = api.store("agent-a", "High.")
        e3 = api.store("agent-a", "Mid.")
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.3 WHERE id = ?", (e1.id,)
        )
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.9 WHERE id = ?", (e2.id,)
        )
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.6 WHERE id = ?", (e3.id,)
        )
        api._conn.commit()
        results = api.recall("agent-a")
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].id == e2.id
        assert results[1].id == e3.id
        assert results[2].id == e1.id

    def test_recall_empty_when_no_matches(self, api: MemoryAPI) -> None:
        api.store("agent-a", "Some content.")
        results = api.recall("nonexistent-agent")
        assert results == []


class TestForget:
    def test_forget_deletes_entry(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "To be forgotten.")
        assert api.forget(entry.id) is True
        results = api.recall("agent-a")
        assert len(results) == 0

    def test_forget_returns_false_for_nonexistent(self, api: MemoryAPI) -> None:
        assert api.forget("nonexistent-id") is False


class TestDecay:
    def test_decay_reduces_relevance_scores(self, api: MemoryAPI) -> None:
        # Create a memory with a timestamp in the past
        entry = api.store("agent-a", "Old memory.")
        old_timestamp = (datetime.now(tz=UTC) - timedelta(days=60)).isoformat()
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?",
            (old_timestamp, entry.id),
        )
        api._conn.commit()

        updated = api.decay()
        assert updated == 1

        results = api.recall("agent-a")
        assert len(results) == 1
        # After 60 days with 30-day half-life, score should be ~0.25
        assert results[0].relevance_score < 0.5

    def test_decay_by_agent_name(self, api: MemoryAPI) -> None:
        e_a = api.store("agent-a", "Memory A.")
        e_b = api.store("agent-b", "Memory B.")
        old_ts = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, e_a.id)
        )
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, e_b.id)
        )
        api._conn.commit()

        # Decay only agent-a
        updated = api.decay(agent_name="agent-a")
        assert updated == 1

        results_a = api.recall("agent-a")
        results_b = api.recall("agent-b")
        # agent-a was decayed
        assert results_a[0].relevance_score < 1.0
        # agent-b was NOT decayed (still has original score of 1.0)
        assert results_b[0].relevance_score == 1.0

    def test_decay_skips_entries_without_timestamp(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "No timestamp entry.")
        # Remove the timestamp
        api._conn.execute(
            "UPDATE memory SET created_at = '' WHERE id = ?", (entry.id,)
        )
        api._conn.commit()

        updated = api.decay()
        assert updated == 0

        results = api.recall("agent-a")
        assert results[0].relevance_score == 1.0

    def test_decay_recent_entry_stays_near_one(self, api: MemoryAPI) -> None:
        # A very recent entry should barely decay
        api.store("agent-a", "Fresh memory.")
        updated = api.decay()
        assert updated == 1
        results = api.recall("agent-a")
        assert results[0].relevance_score > 0.99


class TestPrune:
    def test_prune_removes_low_relevance(self, api: MemoryAPI) -> None:
        e1 = api.store("agent-a", "Keep me.")
        e2 = api.store("agent-a", "Remove me.")
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.01 WHERE id = ?", (e2.id,)
        )
        api._conn.commit()

        pruned = api.prune(min_relevance=0.1)
        assert pruned == 1
        results = api.recall("agent-a")
        assert len(results) == 1
        assert results[0].id == e1.id

    def test_prune_removes_old_entries(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Ancient memory.")
        old_ts = (datetime.now(tz=UTC) - timedelta(days=365)).isoformat()
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, entry.id)
        )
        api._conn.commit()

        pruned = api.prune(max_age_days=30)
        assert pruned == 1
        results = api.recall("agent-a")
        assert len(results) == 0

    def test_prune_by_agent_name(self, api: MemoryAPI) -> None:
        e_a = api.store("agent-a", "Low A.")
        e_b = api.store("agent-b", "Low B.")
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.01 WHERE id = ?", (e_a.id,)
        )
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.01 WHERE id = ?", (e_b.id,)
        )
        api._conn.commit()

        pruned = api.prune(agent_name="agent-a", min_relevance=0.1)
        assert pruned == 1
        # agent-b should still exist
        results_b = api.recall("agent-b")
        assert len(results_b) == 1

    def test_prune_default_threshold(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Below threshold.")
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.05 WHERE id = ?", (entry.id,)
        )
        api._conn.commit()

        # No min_relevance or max_age_days => uses PRUNE_THRESHOLD (0.1)
        pruned = api.prune()
        assert pruned == 1

    def test_prune_keeps_entries_above_threshold(self, api: MemoryAPI) -> None:
        entry = api.store("agent-a", "Above threshold.")
        api._conn.execute(
            "UPDATE memory SET relevance_score = 0.5 WHERE id = ?", (entry.id,)
        )
        api._conn.commit()

        pruned = api.prune()
        assert pruned == 0
        results = api.recall("agent-a")
        assert len(results) == 1

    def test_prune_max_age_does_not_affect_recent(self, api: MemoryAPI) -> None:
        api.store("agent-a", "Recent memory.")
        pruned = api.prune(max_age_days=1)
        assert pruned == 0

    def test_prune_combines_age_and_agent_filter(self, api: MemoryAPI) -> None:
        e_a = api.store("agent-a", "Old A.")
        e_b = api.store("agent-b", "Old B.")
        old_ts = (datetime.now(tz=UTC) - timedelta(days=100)).isoformat()
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, e_a.id)
        )
        api._conn.execute(
            "UPDATE memory SET created_at = ? WHERE id = ?", (old_ts, e_b.id)
        )
        api._conn.commit()

        pruned = api.prune(agent_name="agent-a", max_age_days=30)
        assert pruned == 1
        # agent-b should still be there
        assert len(api.recall("agent-b")) == 1


class TestStoreRecallRoundTrip:
    def test_store_then_recall_roundtrip(self, api: MemoryAPI) -> None:
        stored = api.store(
            "agent-a",
            "Important lesson learned.",
            memory_type="episodic",
            context='{"plan": "deploy"}',
        )
        recalled = api.recall("agent-a")
        assert len(recalled) == 1
        r = recalled[0]
        assert r.id == stored.id
        assert r.agent_name == stored.agent_name
        assert r.content == stored.content
        assert r.memory_type == stored.memory_type
        assert r.context == stored.context
        assert r.created_at == stored.created_at
        assert r.relevance_score == stored.relevance_score
