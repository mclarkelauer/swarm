"""Tests for swarm.config: SwarmConfig, load_config, save_config."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.config import SwarmConfig, load_config, save_config
from swarm.errors import ConfigError


class TestLoadConfigDefaults:
    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent.json")
        defaults = SwarmConfig()
        assert config.forge_timeout == defaults.forge_timeout

    def test_default_base_dir_is_path_object(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "missing.json")
        assert isinstance(config.base_dir, Path)


class TestLoadConfigFromFile:
    def test_loads_all_fields(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"base_dir": "/tmp/mybase", "forge_timeout": 300}',
            encoding="utf-8",
        )
        config = load_config(cfg_file)
        assert config.base_dir == Path("/tmp/mybase")
        assert config.forge_timeout == 300

    def test_base_dir_is_path_object(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"base_dir": "/some/path"}', encoding="utf-8")
        config = load_config(cfg_file)
        assert isinstance(config.base_dir, Path)
        assert config.base_dir == Path("/some/path")


class TestSaveAndReload:
    def test_round_trip_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.json"
        original = SwarmConfig()
        save_config(original, cfg_file)
        reloaded = load_config(cfg_file)
        assert reloaded.base_dir == original.base_dir
        assert reloaded.forge_timeout == original.forge_timeout

    def test_round_trip_custom_values(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.json"
        original = SwarmConfig(
            base_dir=tmp_path / "custom",
            forge_timeout=120,
        )
        save_config(original, cfg_file)
        reloaded = load_config(cfg_file)
        assert reloaded.base_dir == tmp_path / "custom"
        assert reloaded.forge_timeout == 120

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "config.json"
        save_config(SwarmConfig(), nested)
        assert nested.exists()


class TestInvalidJson:
    def test_raises_config_error_on_invalid_json(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bad.json"
        cfg_file.write_text("{not valid json}", encoding="utf-8")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(cfg_file)

    def test_raises_config_error_on_non_object_json(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "array.json"
        cfg_file.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(cfg_file)


class TestMissingKeys:
    def test_missing_forge_timeout_uses_default(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "partial.json"
        cfg_file.write_text('{"base_dir": "/tmp/x"}', encoding="utf-8")
        config = load_config(cfg_file)
        assert config.forge_timeout == SwarmConfig().forge_timeout

    def test_empty_object_uses_all_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "empty.json"
        cfg_file.write_text("{}", encoding="utf-8")
        config = load_config(cfg_file)
        defaults = SwarmConfig()
        assert config.forge_timeout == defaults.forge_timeout


class TestExtraKeys:
    def test_extra_keys_ignored(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "extra.json"
        cfg_file.write_text(
            '{"forge_timeout": 60, "unknown_future_key": "value"}',
            encoding="utf-8",
        )
        config = load_config(cfg_file)
        assert config.forge_timeout == 60
        assert not hasattr(config, "unknown_future_key")
