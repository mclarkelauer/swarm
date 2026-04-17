"""Shared helpers for CLI command modules."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from swarm.config import load_config
from swarm.dirs import ensure_base_dir
from swarm.forge.api import ForgeAPI
from swarm.registry.api import RegistryAPI


def get_registry() -> RegistryAPI:
    """Return a :class:`RegistryAPI` using the default config.

    Caller is responsible for ``close()``.  Prefer
    :func:`open_registry` as a context manager.
    """
    config = load_config()
    return RegistryAPI(config.base_dir / "registry.db")


def get_forge() -> ForgeAPI:
    """Return a :class:`ForgeAPI` using the default config.

    Caller is responsible for ``close()``.  Prefer
    :func:`open_forge` as a context manager.
    """
    config = load_config()
    ensure_base_dir(config.base_dir)
    return ForgeAPI(config.base_dir / "registry.db", config.base_dir / "forge")


@contextmanager
def open_registry() -> Iterator[RegistryAPI]:
    """Context-managed :class:`RegistryAPI` that closes on exit."""
    api = get_registry()
    try:
        yield api
    finally:
        api.close()


@contextmanager
def open_forge() -> Iterator[ForgeAPI]:
    """Context-managed :class:`ForgeAPI` that closes on exit."""
    api = get_forge()
    try:
        yield api
    finally:
        api.close()
