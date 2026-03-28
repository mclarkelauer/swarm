"""Tests for swarm.plan.versioning: next_version, list_versions, load_version."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.plan.models import Plan, PlanStep
from swarm.plan.versioning import list_versions, load_version, next_version


def _write_plan(instance_dir: Path, version: int) -> None:
    plan = Plan(
        version=version,
        goal=f"goal v{version}",
        steps=[PlanStep(id="s1", type="task", prompt="p", agent_type="w")],
    )
    path = instance_dir / f"plan_v{version}.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")


class TestListVersions:
    def test_empty_directory(self, tmp_path: Path) -> None:
        assert list_versions(tmp_path) == []

    def test_finds_versions(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 1)
        _write_plan(tmp_path, 2)
        assert list_versions(tmp_path) == [1, 2]

    def test_sorted_order(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 3)
        _write_plan(tmp_path, 1)
        _write_plan(tmp_path, 2)
        assert list_versions(tmp_path) == [1, 2, 3]

    def test_ignores_non_plan_files(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 1)
        (tmp_path / "other.json").write_text("{}", encoding="utf-8")
        assert list_versions(tmp_path) == [1]

    def test_missing_directory(self, tmp_path: Path) -> None:
        assert list_versions(tmp_path / "nonexistent") == []


class TestNextVersion:
    def test_first_version(self, tmp_path: Path) -> None:
        assert next_version(tmp_path) == 1

    def test_increments(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 1)
        assert next_version(tmp_path) == 2

    def test_after_multiple(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 1)
        _write_plan(tmp_path, 2)
        _write_plan(tmp_path, 3)
        assert next_version(tmp_path) == 4


class TestLoadVersion:
    def test_loads_correct_version(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, 1)
        _write_plan(tmp_path, 2)
        plan = load_version(tmp_path, 2)
        assert plan.version == 2
        assert plan.goal == "goal v2"

    def test_missing_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_version(tmp_path, 99)
