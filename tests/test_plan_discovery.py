"""Tests for swarm.plan.discovery."""

from __future__ import annotations

from pathlib import Path

from swarm.plan.discovery import find_plans_dir


class TestFindPlansDir:
    def test_finds_dir_with_plan_files(self, tmp_path: Path) -> None:
        (tmp_path / "plan_v1.json").write_text("{}")
        assert find_plans_dir(tmp_path) == tmp_path

    def test_finds_dot_swarm_marker(self, tmp_path: Path) -> None:
        (tmp_path / ".swarm").mkdir()
        assert find_plans_dir(tmp_path) == tmp_path

    def test_returns_none_when_nothing_found(self, tmp_path: Path) -> None:
        child = tmp_path / "deep" / "nested"
        child.mkdir(parents=True)
        assert find_plans_dir(child) is None

    def test_finds_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / "plan_v1.json").write_text("{}")
        child = tmp_path / "subdir"
        child.mkdir()
        assert find_plans_dir(child) == tmp_path

    def test_prefers_current_over_parent(self, tmp_path: Path) -> None:
        (tmp_path / "plan_v1.json").write_text("{}")
        child = tmp_path / "inner"
        child.mkdir()
        (child / "plan_v2.json").write_text("{}")
        assert find_plans_dir(child) == child
