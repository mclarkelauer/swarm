"""Tests for swarm.registry.db: init_registry_db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from swarm.registry.db import init_registry_db


class TestInitRegistryDb:
    """Database initialization and schema tests."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        init_registry_db(db_path)
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_agents_table_exists(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agents'"
        )
        assert cur.fetchone() is not None

    def test_insert_and_retrieve(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
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
        conn, _ = init_registry_db(tmp_path / "registry.db")
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
        conn1, _ = init_registry_db(db_path)
        conn1.execute(
            "INSERT INTO agents (id, name, system_prompt) VALUES ('x', 'x', 'p')"
        )
        conn1.commit()
        conn1.close()
        conn2, _ = init_registry_db(db_path)
        cur = conn2.execute("SELECT id FROM agents WHERE id = 'x'")
        assert cur.fetchone() is not None


class TestMigration:
    """Tests for the ALTER TABLE migration that adds description and tags columns."""

    def _create_old_schema_db(self, db_path: Path) -> sqlite3.Connection:
        """Create a DB with the pre-Tier1 schema (no description or tags columns)."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                parent_id   TEXT,
                system_prompt TEXT NOT NULL DEFAULT '',
                tools       TEXT NOT NULL DEFAULT '[]',
                permissions TEXT NOT NULL DEFAULT '[]',
                working_dir TEXT NOT NULL DEFAULT '',
                source      TEXT NOT NULL DEFAULT 'forge',
                created_at  TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (parent_id) REFERENCES agents(id)
            )
            """
        )
        conn.commit()
        return conn

    def test_migration_adds_columns(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old_registry.db"

        # Create DB with old schema and seed a row
        old_conn = self._create_old_schema_db(db_path)
        old_conn.execute(
            "INSERT INTO agents (id, name, system_prompt) VALUES ('a1', 'existing', 'old prompt')"
        )
        old_conn.commit()
        old_conn.close()

        # Run init_registry_db on the existing DB — should add missing columns
        new_conn, _ = init_registry_db(db_path)

        # Both new columns must exist now
        col_info = new_conn.execute("PRAGMA table_info(agents)").fetchall()
        col_names = {row[1] for row in col_info}
        assert "description" in col_names
        assert "tags" in col_names

        # Existing row still readable and new fields have defaults
        row = new_conn.execute(
            "SELECT description, tags FROM agents WHERE id = 'a1'"
        ).fetchone()
        assert row is not None
        assert row[0] == ""    # description default
        assert row[1] == "[]"  # tags default

        # New insert with all fields works
        new_conn.execute(
            "INSERT INTO agents (id, name, system_prompt, description, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a2", "new-agent", "prompt", "my description", '["tag1","tag2"]'),
        )
        new_conn.commit()
        row2 = new_conn.execute(
            "SELECT description, tags FROM agents WHERE id = 'a2'"
        ).fetchone()
        assert row2 is not None
        assert row2[0] == "my description"
        assert row2[1] == '["tag1","tag2"]'

    def test_migration_adds_performance_columns(self, tmp_path: Path) -> None:
        """Running init_registry_db on a pre-Tier2 DB adds the four new columns."""
        db_path = tmp_path / "old_registry.db"

        # Create a DB that only has the Tier1 schema (no performance columns)
        old_conn = self._create_old_schema_db(db_path)
        old_conn.execute("ALTER TABLE agents ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        old_conn.execute("ALTER TABLE agents ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        old_conn.execute(
            "INSERT INTO agents (id, name, system_prompt) VALUES ('b1', 'existing', 'old prompt')"
        )
        old_conn.commit()
        old_conn.close()

        # Apply current init_registry_db — must add the four new columns
        new_conn, _ = init_registry_db(db_path)

        col_info = new_conn.execute("PRAGMA table_info(agents)").fetchall()
        col_names = {row[1] for row in col_info}
        assert "usage_count" in col_names
        assert "failure_count" in col_names
        assert "last_used" in col_names
        assert "notes" in col_names

        # Existing row must have correct defaults after migration
        row = new_conn.execute(
            "SELECT usage_count, failure_count, last_used, notes FROM agents WHERE id = 'b1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0    # usage_count default
        assert row[1] == 0    # failure_count default
        assert row[2] == ""   # last_used default
        assert row[3] == ""   # notes default

    def test_new_schema_includes_performance_columns(self, tmp_path: Path) -> None:
        """A freshly created database already has all performance columns."""
        conn, _ = init_registry_db(tmp_path / "fresh.db")
        col_info = conn.execute("PRAGMA table_info(agents)").fetchall()
        col_names = {row[1] for row in col_info}
        for col in ("usage_count", "failure_count", "last_used", "notes"):
            assert col in col_names

    def test_insert_with_performance_fields(self, tmp_path: Path) -> None:
        conn, _ = init_registry_db(tmp_path / "registry.db")
        conn.execute(
            "INSERT INTO agents (id, name, system_prompt, usage_count, failure_count, last_used, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("p1", "perf-agent", "prompt", 10, 2, "2026-01-01T00:00:00", "some notes"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT usage_count, failure_count, last_used, notes FROM agents WHERE id = 'p1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 10
        assert row[1] == 2
        assert row[2] == "2026-01-01T00:00:00"
        assert row[3] == "some notes"
