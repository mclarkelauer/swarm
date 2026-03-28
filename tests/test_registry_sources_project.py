"""Tests for swarm.registry.sources.project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.errors import RegistryError
from swarm.registry.sources.project import ProjectDirectorySource


def _write_agent(agents_dir: Path, name: str, prompt: str = "prompt") -> Path:
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{name}.agent.json"
    path.write_text(json.dumps({
        "name": name,
        "system_prompt": prompt,
        "tools": ["Read"],
        "permissions": [],
    }))
    return path


class TestProjectDirectorySourceSearch:
    def test_search_finds_agent_json_files(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".swarm" / "agents"
        _write_agent(agents_dir, "reviewer", "Reviews code.")
        source = ProjectDirectorySource(tmp_path)
        results = source.search("review")
        assert len(results) == 1
        assert results[0].name == "reviewer"
        assert results[0].source == "project"

    def test_search_empty_dir(self, tmp_path: Path) -> None:
        source = ProjectDirectorySource(tmp_path)
        assert source.search("anything") == []

    def test_search_skips_malformed(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".swarm" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "bad.agent.json").write_text("not json")
        _write_agent(agents_dir, "good")
        source = ProjectDirectorySource(tmp_path)
        results = source.search("")
        assert len(results) == 1
        assert results[0].name == "good"


class TestProjectDirectorySourceInstall:
    def test_install_by_name(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".swarm" / "agents"
        _write_agent(agents_dir, "my-agent")
        source = ProjectDirectorySource(tmp_path)
        defn = source.install("my-agent")
        assert defn.name == "my-agent"

    def test_install_missing_raises(self, tmp_path: Path) -> None:
        source = ProjectDirectorySource(tmp_path)
        with pytest.raises(RegistryError, match="not found"):
            source.install("nonexistent")


class TestDeterministicIds:
    def test_same_file_same_id(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".swarm" / "agents"
        _write_agent(agents_dir, "stable-agent")
        source = ProjectDirectorySource(tmp_path)
        results1 = source.search("")
        results2 = source.search("")
        assert results1[0].id == results2[0].id
