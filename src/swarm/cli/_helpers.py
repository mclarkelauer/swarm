"""Shared helpers for CLI command modules."""

from __future__ import annotations

from swarm.config import load_config
from swarm.dirs import ensure_base_dir
from swarm.forge.api import ForgeAPI
from swarm.registry.api import RegistryAPI


def get_registry() -> RegistryAPI:
    """Return a :class:`RegistryAPI` using the default config."""
    config = load_config()
    return RegistryAPI(config.base_dir / "registry.db")


def get_forge() -> ForgeAPI:
    """Return a :class:`ForgeAPI` using the default config."""
    config = load_config()
    ensure_base_dir(config.base_dir)
    return ForgeAPI(config.base_dir / "registry.db", config.base_dir / "forge")
