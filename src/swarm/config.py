"""Configuration management for Swarm.

Loads and saves ``SwarmConfig`` from/to a JSON file at ``~/.swarm/config.json``
(or an explicitly provided path).  Missing keys fall back to dataclass defaults;
extra keys in the JSON file are silently ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from swarm.errors import ConfigError

_DEFAULT_CONFIG_PATH = Path.home() / ".swarm" / "config.json"


@dataclass(frozen=True)
class SwarmConfig:
    """Global configuration for the Swarm system.

    Attributes:
        base_dir: Root directory for all Swarm data.
        forge_timeout: Seconds before ``swarm forge design`` times out.
    """

    base_dir: Path = field(default_factory=lambda: Path.home() / ".swarm")
    forge_timeout: int = 600
    agent_timeout: int = 300
    max_concurrent_background: int = 4


def _config_path(path: Path | None) -> Path:
    return path if path is not None else _DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> SwarmConfig:
    """Load ``SwarmConfig`` from a JSON file.

    Returns defaults when the file does not exist.  Missing keys in the file
    fall back to dataclass defaults; extra keys are silently ignored.

    Args:
        path: Explicit path to the config file.  Defaults to
            ``~/.swarm/config.json``.

    Returns:
        A fully-populated ``SwarmConfig`` instance.

    Raises:
        ConfigError: If the file exists but contains invalid JSON.
    """
    config_path = _config_path(path)

    if not config_path.exists():
        return SwarmConfig()

    try:
        raw: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config file {config_path} must contain a JSON object, got {type(raw).__name__}"
        )

    # Collect the names of known fields so we can filter out extras.
    known: set[str] = {f.name for f in fields(SwarmConfig)}
    filtered: dict[str, Any] = {k: v for k, v in raw.items() if k in known}

    # Deserialize base_dir from string back to Path.
    if "base_dir" in filtered:
        filtered["base_dir"] = Path(filtered["base_dir"])

    defaults = SwarmConfig()
    kwargs: dict[str, Any] = {}
    for f in fields(SwarmConfig):
        if f.name in filtered:
            kwargs[f.name] = filtered[f.name]
        else:
            kwargs[f.name] = getattr(defaults, f.name)

    return SwarmConfig(**kwargs)


def save_config(config: SwarmConfig, path: Path | None = None) -> None:
    """Save ``SwarmConfig`` to a JSON file.

    The parent directory is created if it does not yet exist.

    Args:
        config: The configuration instance to save.
        path: Explicit destination path.  Defaults to ``~/.swarm/config.json``.
    """
    config_path = _config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "base_dir": str(config.base_dir),
        "forge_timeout": config.forge_timeout,
        "agent_timeout": config.agent_timeout,
        "max_concurrent_background": config.max_concurrent_background,
    }

    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
