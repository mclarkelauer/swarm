"""Tests for swarm.memory.db: init_memory_db."""

from __future__ import annotations

from pathlib import Path

from swarm.memory.db import init_memory_db


class TestInitMemoryDb:
    """Database initialization and schema tests."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        conn, _ = init_memory_db(db_path)
        try:
            assert db_path.exists()
        finally:
            conn.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        conn, _ = init_memory_db(tmp_path / "memory.db")
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()

    def test_memory_table_exists(self, tmp_path: Path) -> None:
        conn, _ = init_memory_db(tmp_path / "memory.db")
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory'"
            )
            assert cur.fetchone() is not None
        finally:
            conn.close()

    def test_insert_and_retrieve(self, tmp_path: Path) -> None:
        conn, _ = init_memory_db(tmp_path / "memory.db")
        try:
            conn.execute(
                "INSERT INTO memory (id, agent_name, memory_type, content, "
                "context, created_at, relevance_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("id1", "test-agent", "semantic", "some fact", "", "2026-01-01", 1.0),
            )
            conn.commit()
            cur = conn.execute("SELECT content FROM memory WHERE id = 'id1'")
            assert cur.fetchone()[0] == "some fact"
        finally:
            conn.close()

    def test_idempotent_initialization(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        conn1, _ = init_memory_db(db_path)
        conn1.execute(
            "INSERT INTO memory (id, agent_name, content) VALUES ('x', 'agent', 'fact')"
        )
        conn1.commit()
        conn1.close()
        conn2, _ = init_memory_db(db_path)
        try:
            cur = conn2.execute("SELECT id FROM memory WHERE id = 'x'")
            assert cur.fetchone() is not None
        finally:
            conn2.close()

    def test_indexes_created(self, tmp_path: Path) -> None:
        conn, _ = init_memory_db(tmp_path / "memory.db")
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_memory%'"
            )
            index_names = {row[0] for row in cur.fetchall()}
            assert "idx_memory_agent_name" in index_names
            assert "idx_memory_type" in index_names
            assert "idx_memory_relevance" in index_names
        finally:
            conn.close()

    def test_fts_table_created_when_available(self, tmp_path: Path) -> None:
        conn, fts_available = init_memory_db(tmp_path / "memory.db")
        try:
            if fts_available:
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
                )
                assert cur.fetchone() is not None
        finally:
            conn.close()

    def test_returns_fts_available_flag(self, tmp_path: Path) -> None:
        conn, fts_available = init_memory_db(tmp_path / "memory.db")
        try:
            # FTS5 is available on most modern SQLite builds; just verify it's a bool
            assert isinstance(fts_available, bool)
        finally:
            conn.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = tmp_path / "a" / "b" / "memory.db"
        conn, _ = init_memory_db(db_path)
        assert db_path.exists()
        conn.close()

    def test_memory_table_columns(self, tmp_path: Path) -> None:
        conn, _ = init_memory_db(tmp_path / "memory.db")
        try:
            col_info = conn.execute("PRAGMA table_info(memory)").fetchall()
            col_names = {row[1] for row in col_info}
            expected = {
                "id", "agent_name", "memory_type", "content",
                "context", "created_at", "relevance_score",
            }
            assert expected.issubset(col_names)
        finally:
            conn.close()
