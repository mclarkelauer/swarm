"""Tests for swarm.dirs: ensure_base_dir."""

from __future__ import annotations

from pathlib import Path

from swarm.dirs import ensure_base_dir


class TestEnsureBaseDir:
    def test_creates_base_directory(self, tmp_path: Path) -> None:
        base = tmp_path / "swarm"
        ensure_base_dir(base)
        assert base.is_dir()

    def test_creates_forge_subdirectory(self, tmp_path: Path) -> None:
        base = tmp_path / "swarm"
        ensure_base_dir(base)
        assert (base / "forge").is_dir()

    def test_idempotent_on_repeated_calls(self, tmp_path: Path) -> None:
        base = tmp_path / "swarm"
        ensure_base_dir(base)
        ensure_base_dir(base)
        assert (base / "forge").is_dir()

    def test_creates_nested_base_if_needed(self, tmp_path: Path) -> None:
        base = tmp_path / "a" / "b" / "swarm"
        ensure_base_dir(base)
        assert base.is_dir()
