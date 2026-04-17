"""Tests for swarm.memory.similarity: TF-IDF similarity search."""

from __future__ import annotations

import pytest

from swarm.memory.similarity import (
    _cosine_similarity,
    _term_frequency,
    _tokenize,
    similarity_search,
)


class TestTokenize:
    def test_basic(self) -> None:
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self) -> None:
        assert _tokenize("it's a test!") == ["it", "s", "a", "test"]

    def test_empty(self) -> None:
        assert _tokenize("") == []


class TestTermFrequency:
    def test_basic(self) -> None:
        tf = _term_frequency(["a", "b", "a"])
        assert tf["a"] == pytest.approx(2 / 3)
        assert tf["b"] == pytest.approx(1 / 3)

    def test_empty(self) -> None:
        assert _term_frequency([]) == {}


class TestCosineSimilarity:
    def test_identical(self) -> None:
        vec = {"a": 1.0, "b": 2.0}
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal(self) -> None:
        va = {"a": 1.0}
        vb = {"b": 1.0}
        assert _cosine_similarity(va, vb) == pytest.approx(0.0)

    def test_empty(self) -> None:
        assert _cosine_similarity({}, {"a": 1.0}) == 0.0


class TestSimilaritySearch:
    def test_finds_similar_documents(self) -> None:
        docs = [
            "Python testing with pytest fixtures",
            "JavaScript React component rendering",
            "Python unit test best practices",
            "Database schema migration guide",
        ]
        results = similarity_search("python test", docs)
        assert len(results) > 0
        # Python testing docs should rank higher
        top_idx = results[0][0]
        assert top_idx in (0, 2)

    def test_respects_top_k(self) -> None:
        docs = ["doc one", "doc two", "doc three"]
        results = similarity_search("doc", docs, top_k=2)
        assert len(results) <= 2

    def test_respects_min_score(self) -> None:
        docs = ["completely unrelated text about cooking"]
        results = similarity_search("python programming", docs, min_score=0.5)
        assert len(results) == 0

    def test_empty_query(self) -> None:
        assert similarity_search("", ["doc"]) == []

    def test_empty_documents(self) -> None:
        assert similarity_search("query", []) == []

    def test_exact_match_scores_high(self) -> None:
        docs = ["python testing", "java testing", "ruby testing"]
        results = similarity_search("python testing", docs)
        assert results[0][0] == 0  # Exact match is first
        assert results[0][1] > 0.5  # High score


class TestRecallSimilar:
    def test_recall_similar_finds_related_memories(self, tmp_path) -> None:
        from swarm.memory.api import MemoryAPI

        with MemoryAPI(tmp_path / "mem.db") as api:
            api.store("agent", "Always use pytest fixtures for test isolation")
            api.store("agent", "Deploy to production on Fridays")
            api.store("agent", "Run pytest with -v flag for verbose output")

            results = api.recall_similar("agent", "how to test with pytest")
            assert len(results) >= 2
            # pytest-related memories should rank higher
            contents = [entry.content for entry, _ in results]
            assert any("pytest" in c for c in contents[:2])

    def test_recall_similar_empty(self, tmp_path) -> None:
        from swarm.memory.api import MemoryAPI

        with MemoryAPI(tmp_path / "mem.db") as api:
            results = api.recall_similar("agent", "anything")
            assert results == []

    def test_recall_similar_respects_min_relevance(self, tmp_path) -> None:
        from swarm.memory.api import MemoryAPI

        with MemoryAPI(tmp_path / "mem.db") as api:
            entry = api.store("agent", "low relevance memory")
            api._conn.execute(
                "UPDATE memory SET relevance_score = 0.05 WHERE id = ?",
                (entry.id,),
            )
            api._conn.commit()

            results = api.recall_similar("agent", "memory", min_relevance=0.1)
            assert len(results) == 0
