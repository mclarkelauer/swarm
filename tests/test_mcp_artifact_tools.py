"""Tests for swarm.mcp.artifact_tools: artifact_declare, artifact_list, artifact_get."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.artifact_tools import artifact_declare, artifact_get, artifact_list


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


class TestArtifactList:
    def test_empty_when_file_missing(self, tmp_path: Path) -> None:
        result = json.loads(artifact_list())
        assert result == []

    def test_returns_empty_string_literal_when_no_file(self, tmp_path: Path) -> None:
        # artifact_list returns the string "[]" when file is absent
        assert artifact_list() == "[]"

    def test_returns_declared_entries(self, tmp_path: Path) -> None:
        artifact_declare("report.md", "Final report", "agent-1")
        artifact_declare("data.csv", "Raw data")
        result = json.loads(artifact_list())
        assert len(result) == 2
        assert result[0]["path"] == "report.md"
        assert result[0]["agent_id"] == "agent-1"
        assert result[1]["path"] == "data.csv"
        assert result[1]["agent_id"] == ""

    def test_explicit_plan_dir(self, tmp_path: Path) -> None:
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        artifacts_file = other_dir / "artifacts.json"
        artifacts_file.write_text(
            json.dumps({"agent_id": "x", "path": "foo.txt", "description": "Foo"}) + "\n"
        )
        result = json.loads(artifact_list(plan_dir=str(other_dir)))
        assert len(result) == 1
        assert result[0]["path"] == "foo.txt"

    def test_skips_corrupt_lines(self, tmp_path: Path) -> None:
        artifacts_file = tmp_path / "artifacts.json"
        good = json.dumps({"agent_id": "", "path": "good.txt", "description": "Good"})
        artifacts_file.write_text(f"{good}\nNOT_JSON\n\n")
        result = json.loads(artifact_list())
        assert len(result) == 1
        assert result[0]["path"] == "good.txt"

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        artifacts_file = tmp_path / "artifacts.json"
        good = json.dumps({"agent_id": "", "path": "a.txt", "description": "A"})
        artifacts_file.write_text(f"\n{good}\n\n")
        result = json.loads(artifact_list())
        assert len(result) == 1


class TestArtifactGet:
    def _write_artifact_file(self, path: Path, lines: int) -> None:
        path.write_text("\n".join(f"line {i}" for i in range(1, lines + 1)))

    def test_file_not_found_no_metadata(self, tmp_path: Path) -> None:
        result = json.loads(artifact_get("missing.txt"))
        assert result["content"] is None
        assert result["metadata"] is None
        assert result["truncated"] is False
        assert "File not found" in result["error"]

    def test_file_not_found_with_metadata(self, tmp_path: Path) -> None:
        artifact_declare("ghost.txt", "Declared but absent", "agent-7")
        result = json.loads(artifact_get("ghost.txt"))
        assert result["content"] is None
        assert result["metadata"]["agent_id"] == "agent-7"
        assert "File not found" in result["error"]

    def test_reads_file_with_metadata(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "report.md"
        self._write_artifact_file(artifact_file, 3)
        artifact_declare(str(artifact_file), "Report", "agent-1")
        result = json.loads(artifact_get(str(artifact_file)))
        assert result["content"] == "line 1\nline 2\nline 3"
        assert result["metadata"]["agent_id"] == "agent-1"
        assert result["truncated"] is False

    def test_truncates_at_max_lines(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "big.txt"
        self._write_artifact_file(artifact_file, 10)
        result = json.loads(artifact_get(str(artifact_file), max_lines="3"))
        assert result["content"] == "line 1\nline 2\nline 3"
        assert result["truncated"] is True

    def test_not_truncated_when_file_equals_max_lines(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "exact.txt"
        self._write_artifact_file(artifact_file, 5)
        result = json.loads(artifact_get(str(artifact_file), max_lines="5"))
        assert result["truncated"] is False

    def test_relative_path_resolved_via_plan_dir(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "relative.txt"
        self._write_artifact_file(artifact_file, 2)
        # Use relative filename only — should resolve via plan_dir
        result = json.loads(artifact_get("relative.txt", plan_dir=str(tmp_path)))
        assert result["content"] == "line 1\nline 2"
        assert result["truncated"] is False

    def test_metadata_null_when_path_not_in_artifacts_json(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "unregistered.txt"
        self._write_artifact_file(artifact_file, 1)
        result = json.loads(artifact_get(str(artifact_file)))
        assert result["metadata"] is None
        assert result["content"] == "line 1"

    def test_default_max_lines_is_50(self, tmp_path: Path) -> None:
        artifact_file = tmp_path / "long.txt"
        self._write_artifact_file(artifact_file, 100)
        result = json.loads(artifact_get(str(artifact_file)))
        returned_lines = result["content"].count("\n") + 1
        assert returned_lines == 50
        assert result["truncated"] is True

    def test_explicit_plan_dir_for_artifacts_json(self, tmp_path: Path) -> None:
        other_dir = tmp_path / "plan"
        other_dir.mkdir()
        artifact_file = other_dir / "out.txt"
        self._write_artifact_file(artifact_file, 2)
        entry = {"agent_id": "z", "path": "out.txt", "description": "Out"}
        (other_dir / "artifacts.json").write_text(json.dumps(entry) + "\n")
        result = json.loads(
            artifact_get("out.txt", plan_dir=str(other_dir))
        )
        assert result["metadata"]["agent_id"] == "z"
        assert result["content"] == "line 1\nline 2"
