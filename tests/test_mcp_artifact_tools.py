"""Tests for swarm.mcp.artifact_tools: artifact_declare."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.artifact_tools import artifact_declare


@pytest.fixture(autouse=True)
def _setup_plans_dir(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)


class TestArtifactDeclare:
    def test_returns_ok(self, tmp_path: Path) -> None:
        result = json.loads(artifact_declare("/out/report.md", "Final report", "agent-1"))
        assert result["ok"] is True
        assert result["artifact"]["agent_id"] == "agent-1"
        assert result["artifact"]["path"] == "/out/report.md"

    def test_agent_id_optional(self, tmp_path: Path) -> None:
        result = json.loads(artifact_declare("file.txt", "A file"))
        assert result["ok"] is True
        assert result["artifact"]["agent_id"] == ""

    def test_appends_to_artifacts_file(self, tmp_path: Path) -> None:
        artifact_declare("file1.txt", "First", "agent-1")
        artifact_declare("file2.txt", "Second", "agent-2")
        artifacts_path = tmp_path / "artifacts.json"
        lines = artifacts_path.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["agent_id"] == "agent-1"

    def test_creates_artifacts_file_if_missing(self, tmp_path: Path) -> None:
        artifacts_path = tmp_path / "artifacts.json"
        assert not artifacts_path.exists()
        artifact_declare("file.txt", "A file")
        assert artifacts_path.exists()
