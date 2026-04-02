"""Tests for swarm.memory.models: MemoryEntry."""

from __future__ import annotations

import pytest

from swarm.memory.models import MemoryEntry


class TestMemoryEntryConstruction:
    def test_memory_entry_construction(self) -> None:
        entry = MemoryEntry(
            id="abc-123",
            agent_name="code-reviewer",
            content="Always check error handling.",
            memory_type="semantic",
            context='{"step_id": "s1"}',
            created_at="2026-01-01T00:00:00+00:00",
            relevance_score=0.9,
        )
        assert entry.id == "abc-123"
        assert entry.agent_name == "code-reviewer"
        assert entry.content == "Always check error handling."
        assert entry.memory_type == "semantic"
        assert entry.context == '{"step_id": "s1"}'
        assert entry.created_at == "2026-01-01T00:00:00+00:00"
        assert entry.relevance_score == 0.9

    def test_memory_entry_defaults(self) -> None:
        entry = MemoryEntry(id="x", agent_name="agent", content="fact")
        assert entry.memory_type == "semantic"
        assert entry.context == ""
        assert entry.created_at == ""
        assert entry.relevance_score == 1.0


class TestMemoryEntryRoundTrip:
    def test_memory_entry_roundtrip(self) -> None:
        entry = MemoryEntry(
            id="r1",
            agent_name="researcher",
            content="Use structured output.",
            memory_type="procedural",
            context='{"plan": "build"}',
            created_at="2026-03-15T12:00:00+00:00",
            relevance_score=0.75,
        )
        d = entry.to_dict()
        restored = MemoryEntry.from_dict(d)
        assert restored.id == entry.id
        assert restored.agent_name == entry.agent_name
        assert restored.content == entry.content
        assert restored.memory_type == entry.memory_type
        assert restored.context == entry.context
        assert restored.created_at == entry.created_at
        assert restored.relevance_score == entry.relevance_score


class TestMemoryEntrySpareSerialization:
    def test_default_memory_type_omitted(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", memory_type="semantic")
        d = entry.to_dict()
        assert "memory_type" not in d

    def test_non_default_memory_type_included(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", memory_type="episodic")
        d = entry.to_dict()
        assert d["memory_type"] == "episodic"

    def test_default_relevance_omitted(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", relevance_score=1.0)
        d = entry.to_dict()
        assert "relevance_score" not in d

    def test_non_default_relevance_included(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", relevance_score=0.5)
        d = entry.to_dict()
        assert d["relevance_score"] == 0.5

    def test_empty_context_omitted(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", context="")
        d = entry.to_dict()
        assert "context" not in d

    def test_non_empty_context_included(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", context="ctx")
        d = entry.to_dict()
        assert d["context"] == "ctx"

    def test_empty_created_at_omitted(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", created_at="")
        d = entry.to_dict()
        assert "created_at" not in d

    def test_non_empty_created_at_included(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c", created_at="2026-01-01")
        d = entry.to_dict()
        assert d["created_at"] == "2026-01-01"

    def test_all_defaults_minimal_dict(self) -> None:
        entry = MemoryEntry(id="s1", agent_name="a", content="c")
        d = entry.to_dict()
        assert set(d.keys()) == {"id", "agent_name", "content"}


class TestMemoryEntryFromDictBackwardCompat:
    def test_missing_optional_fields(self) -> None:
        d = {"id": "old-id", "agent_name": "old-agent", "content": "old content"}
        entry = MemoryEntry.from_dict(d)
        assert entry.memory_type == "semantic"
        assert entry.context == ""
        assert entry.created_at == ""
        assert entry.relevance_score == 1.0

    def test_partial_optional_fields(self) -> None:
        d = {
            "id": "partial",
            "agent_name": "agent",
            "content": "fact",
            "memory_type": "episodic",
        }
        entry = MemoryEntry.from_dict(d)
        assert entry.memory_type == "episodic"
        assert entry.context == ""
        assert entry.relevance_score == 1.0


class TestMemoryEntryFrozen:
    def test_cannot_assign_attributes(self) -> None:
        entry = MemoryEntry(id="f1", agent_name="agent", content="content")
        with pytest.raises(AttributeError):
            entry.content = "modified"  # type: ignore[misc]

    def test_cannot_assign_id(self) -> None:
        entry = MemoryEntry(id="f1", agent_name="agent", content="content")
        with pytest.raises(AttributeError):
            entry.id = "new-id"  # type: ignore[misc]

    def test_cannot_assign_relevance_score(self) -> None:
        entry = MemoryEntry(id="f1", agent_name="agent", content="content")
        with pytest.raises(AttributeError):
            entry.relevance_score = 0.5  # type: ignore[misc]
