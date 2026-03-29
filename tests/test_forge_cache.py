"""Tests for swarm.forge.cache: read_cache, write_cache."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.forge.cache import read_cache, write_cache
from swarm.registry.models import AgentDefinition


def _make_defn(name: str = "test-agent") -> AgentDefinition:
    return AgentDefinition(
        id="test-id",
        name=name,
        system_prompt="You are a test.",
        tools=("bash",),
        permissions=("read",),
        source="forge",
        created_at="2024-01-01T00:00:00",
    )


class TestWriteAndReadCache:
    def test_round_trip(self, tmp_path: Path) -> None:
        defn = _make_defn()
        write_cache(tmp_path, defn)
        result = read_cache(tmp_path, "test-agent")
        assert result is not None
        assert result.name == "test-agent"
        assert result.id == "test-id"

    def test_creates_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "nested" / "cache"
        write_cache(cache_dir, _make_defn())
        assert cache_dir.is_dir()

    def test_cache_miss(self, tmp_path: Path) -> None:
        assert read_cache(tmp_path, "nonexistent") is None

    def test_corrupted_cache(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        assert read_cache(tmp_path, "bad") is None

    def test_overwrite(self, tmp_path: Path) -> None:
        write_cache(tmp_path, _make_defn())
        updated = AgentDefinition(
            id="new-id", name="test-agent", system_prompt="Updated.",
            tools=(), permissions=(), source="forge", created_at="2024-01-02",
        )
        write_cache(tmp_path, updated)
        result = read_cache(tmp_path, "test-agent")
        assert result is not None
        assert result.id == "new-id"


class TestCacheNewFields:
    def test_cache_roundtrip_with_new_fields(self, tmp_path: Path) -> None:
        defn = AgentDefinition(
            id="rich-id",
            name="rich-agent",
            system_prompt="Rich prompt.",
            tools=("bash",),
            permissions=("read",),
            source="forge",
            created_at="2024-01-01T00:00:00",
            description="A well-described agent",
            tags=("python", "review"),
        )
        write_cache(tmp_path, defn)
        result = read_cache(tmp_path, "rich-agent")
        assert result is not None
        assert result.description == "A well-described agent"
        assert result.tags == ("python", "review")

    def test_cache_read_old_format(self, tmp_path: Path) -> None:
        # Manually write a cache file that has no description or tags keys
        old_data = {
            "id": "old-id",
            "name": "old-agent",
            "parent_id": None,
            "system_prompt": "Old prompt.",
            "tools": [],
            "permissions": [],
            "working_dir": "",
            "source": "forge",
            "created_at": "2024-01-01T00:00:00",
            # description and tags intentionally absent
        }
        (tmp_path / "old-agent.json").write_text(
            json.dumps(old_data), encoding="utf-8"
        )
        result = read_cache(tmp_path, "old-agent")
        assert result is not None
        assert result.description == ""
        assert result.tags == ()
