"""Tests for swarm.registry.db: init_registry_db."""

from __future__ import annotations

from pathlib import Path

from swarm.registry.db import init_registry_db


class TestInitRegistryDb:
    """Database initialization and schema tests."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        init_registry_db(db_path)
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        conn = init_registry_db(tmp_path / "registry.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_agents_table_exists(self, tmp_path: Path) -> None:
        conn = init_registry_db(tmp_path / "registry.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agents'"
        )
        assert cur.fetchone() is not None

    def test_insert_and_retrieve(self, tmp_path: Path) -> None:
        conn = init_registry_db(tmp_path / "registry.db")
        conn.execute(
            "INSERT INTO agents (id, name, system_prompt, tools, permissions, "
            "working_dir, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("id1", "test", "prompt", "[]", "[]", "", "forge", "2024-01-01"),
        )
        conn.commit()
        cur = conn.execute("SELECT name FROM agents WHERE id = 'id1'")
        assert cur.fetchone()[0] == "test"

    def test_foreign_key_parent_id(self, tmp_path: Path) -> None:
        conn = init_registry_db(tmp_path / "registry.db")
        # Insert parent
        conn.execute(
            "INSERT INTO agents (id, name, system_prompt) VALUES (?, ?, ?)",
            ("parent", "parent-agent", "prompt"),
        )
        # Insert child referencing parent
        conn.execute(
            "INSERT INTO agents (id, name, parent_id, system_prompt) VALUES (?, ?, ?, ?)",
            ("child", "child-agent", "parent", "prompt"),
        )
        conn.commit()
        cur = conn.execute("SELECT parent_id FROM agents WHERE id = 'child'")
        assert cur.fetchone()[0] == "parent"

    def test_idempotent_initialization(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn1 = init_registry_db(db_path)
        conn1.execute(
            "INSERT INTO agents (id, name, system_prompt) VALUES ('x', 'x', 'p')"
        )
        conn1.commit()
        conn1.close()
        conn2 = init_registry_db(db_path)
        cur = conn2.execute("SELECT id FROM agents WHERE id = 'x'")
        assert cur.fetchone() is not None
