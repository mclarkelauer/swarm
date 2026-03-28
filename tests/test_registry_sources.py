"""Tests for swarm.registry.sources.local: LocalDirectorySource."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.errors import RegistryError
from swarm.registry.sources.local import LocalDirectorySource


@pytest.fixture()
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agents"
    d.mkdir()
    return d


def _write_agent(directory: Path, name: str) -> None:
    data = {
        "id": f"id-{name}",
        "name": name,
        "system_prompt": f"You are a {name}.",
        "tools": ["bash"],
        "permissions": ["read"],
    }
    (directory / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


class TestLocalDirectorySourceSearch:
    def test_search_finds_match(self, source_dir: Path) -> None:
        _write_agent(source_dir, "researcher")
        _write_agent(source_dir, "writer")
        source = LocalDirectorySource(source_dir)
        results = source.search("research")
        assert len(results) == 1
        assert results[0].name == "researcher"

    def test_search_empty_dir(self, source_dir: Path) -> None:
        source = LocalDirectorySource(source_dir)
        assert source.search("anything") == []

    def test_search_missing_dir(self, tmp_path: Path) -> None:
        source = LocalDirectorySource(tmp_path / "nonexistent")
        assert source.search("anything") == []

    def test_search_skips_malformed(self, source_dir: Path) -> None:
        _write_agent(source_dir, "good")
        (source_dir / "bad.json").write_text("{invalid json", encoding="utf-8")
        source = LocalDirectorySource(source_dir)
        results = source.search("")
        assert len(results) == 1
        assert results[0].name == "good"


class TestLocalDirectorySourceInstall:
    def test_install_loads_definition(self, source_dir: Path) -> None:
        _write_agent(source_dir, "researcher")
        source = LocalDirectorySource(source_dir)
        d = source.install("researcher")
        assert d.name == "researcher"
        assert d.id == "id-researcher"

    def test_install_missing_raises(self, source_dir: Path) -> None:
        source = LocalDirectorySource(source_dir)
        with pytest.raises(RegistryError, match="not found"):
            source.install("nonexistent")

    def test_install_malformed_raises(self, source_dir: Path) -> None:
        (source_dir / "bad.json").write_text("not json", encoding="utf-8")
        source = LocalDirectorySource(source_dir)
        with pytest.raises(RegistryError, match="Invalid definition"):
            source.install("bad")
