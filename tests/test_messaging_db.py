"""Tests for swarm.messaging.db: init_message_db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swarm.messaging.db import init_message_db


class TestInitMessageDb:
    """Database initialization and schema tests."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "messages.db"
        conn = init_message_db(db_path)
        conn.close()
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = tmp_path / "a" / "b" / "messages.db"
        conn = init_message_db(db_path)
        conn.close()
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_messages_table_exists(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_messages_table_columns(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        col_info = conn.execute("PRAGMA table_info(messages)").fetchall()
        col_names = {row[1] for row in col_info}
        expected = {
            "id",
            "from_agent",
            "to_agent",
            "step_id",
            "run_id",
            "content",
            "message_type",
            "created_at",
        }
        assert expected.issubset(col_names)
        conn.close()

    def test_indexes_created(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name LIKE 'idx_messages_%'"
        )
        index_names = {row[0] for row in cur.fetchall()}
        assert "idx_messages_run_to_agent" in index_names
        assert "idx_messages_run_step" in index_names
        conn.close()

    def test_idempotent_initialization(self, tmp_path: Path) -> None:
        db_path = tmp_path / "messages.db"
        conn1 = init_message_db(db_path)
        conn1.execute(
            "INSERT INTO messages (id, from_agent, to_agent, message_type) "
            "VALUES ('x', 'a', 'b', 'response')"
        )
        conn1.commit()
        conn1.close()
        # Re-initialize should not raise or lose data
        conn2 = init_message_db(db_path)
        cur = conn2.execute("SELECT id FROM messages WHERE id = 'x'")
        assert cur.fetchone() is not None
        conn2.close()

    def test_insert_and_retrieve(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        conn.execute(
            "INSERT INTO messages (id, from_agent, to_agent, content, message_type) "
            "VALUES (?, ?, ?, ?, ?)",
            ("id1", "agent-a", "agent-b", "hello", "response"),
        )
        conn.commit()
        row = conn.execute("SELECT content FROM messages WHERE id='id1'").fetchone()
        assert row is not None
        assert row[0] == "hello"
        conn.close()

    def test_check_constraint_rejects_invalid_type(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO messages (id, from_agent, to_agent, message_type) "
                    "VALUES (?, ?, ?, ?)",
                    ("id1", "a", "b", "invalid_type"),
                )
        finally:
            conn.close()

    def test_check_constraint_allows_valid_types(self, tmp_path: Path) -> None:
        conn = init_message_db(tmp_path / "messages.db")
        for i, msg_type in enumerate(("request", "response", "broadcast")):
            conn.execute(
                "INSERT INTO messages (id, from_agent, to_agent, message_type) "
                "VALUES (?, ?, ?, ?)",
                (f"id{i}", "a", "b", msg_type),
            )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 3
        conn.close()
