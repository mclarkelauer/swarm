"""Seed the registry with base agents from the built-in catalog.

Base agents use ``source="catalog"`` to distinguish them from user-created
agents (``source="forge"``).  Their IDs are deterministic so they remain stable
across installs and re-seeds:

    uuid5(NAMESPACE_DNS, "swarm-catalog-{name}")

``seed_base_agents()`` is idempotent — safe to call on every process launch.
"""

from __future__ import annotations

import json
import uuid
from typing import TypedDict, cast

from swarm.catalog import ALL_BASE_AGENTS
from swarm.config import load_config
from swarm.registry.api import RegistryAPI

_CATALOG_NAMESPACE = uuid.NAMESPACE_DNS
_PARENT_UPDATED_PREFIX = "[PARENT UPDATED]"


def _catalog_id(name: str) -> str:
    """Return the deterministic UUID for a catalog agent name.

    Args:
        name: Agent name from the catalog (e.g. ``"code-researcher"``).

    Returns:
        A UUID5 string that is stable across installs.
    """
    return str(uuid.uuid5(_CATALOG_NAMESPACE, f"swarm-catalog-{name}"))


class SeedSummary(TypedDict):
    """Summary returned by :func:`seed_base_agents`.

    Attributes:
        created: Names of agents inserted for the first time.
        updated: Names of agents whose system_prompt changed and were updated.
        unchanged: Names of agents that already existed and were current.
    """

    created: list[str]
    updated: list[str]
    unchanged: list[str]


def seed_base_agents(registry: RegistryAPI | None = None) -> SeedSummary:
    """Seed the registry with the built-in base agent catalog.

    For each agent in :data:`~swarm.catalog.ALL_BASE_AGENTS`:

    - If it does not yet exist (by deterministic ID), insert it with
      ``source="catalog"``.
    - If it exists and its ``system_prompt`` is unchanged, leave it alone.
    - If it exists but the ``system_prompt`` has changed (e.g. a new Swarm
      release updated the base agent), update the stored record **and** append
      a ``[PARENT UPDATED]`` notice to every clone that descends from it.

    Args:
        registry: An open :class:`~swarm.registry.api.RegistryAPI` instance.
            When ``None``, one is created from the default config paths.

    Returns:
        A :class:`SeedSummary` dict with ``created``, ``updated``, and
        ``unchanged`` lists of agent names.
    """
    owned_registry = False
    if registry is None:
        config = load_config()
        registry = RegistryAPI(config.base_dir / "registry.db")
        owned_registry = True

    summary: SeedSummary = {"created": [], "updated": [], "unchanged": []}

    try:
        for spec in ALL_BASE_AGENTS:
            name = str(spec["name"])
            system_prompt = str(spec["system_prompt"])
            agent_id = _catalog_id(name)

            existing = registry.get(agent_id)

            if existing is None:
                # First time — insert with deterministic ID
                _insert_catalog_agent(registry, agent_id, spec)
                summary["created"].append(name)
            elif existing.system_prompt == system_prompt:
                # Already current — nothing to do
                summary["unchanged"].append(name)
            else:
                # Base agent was updated in a new release — patch the stored record
                _update_catalog_agent(registry, agent_id, system_prompt)
                _flag_clones(registry, agent_id, name)
                summary["updated"].append(name)
    finally:
        if owned_registry:
            registry.close()

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _insert_catalog_agent(
    registry: RegistryAPI,
    agent_id: str,
    spec: dict[str, object],
) -> None:
    """Insert a catalog agent with a pre-determined ID.

    :class:`~swarm.registry.api.RegistryAPI` always generates a new UUID4 in
    its :meth:`~swarm.registry.api.RegistryAPI.create` method, so we bypass it
    and write directly to the connection that the API wraps.  The connection is
    accessible via the private ``_conn`` attribute; this is an intentional
    internal coupling — the seed module is part of the same package.

    Args:
        registry: Open registry instance.
        agent_id: Pre-computed deterministic UUID5 string.
        spec: Raw agent spec dict from the catalog.
    """
    from datetime import UTC, datetime

    name = str(spec["name"])
    system_prompt = str(spec["system_prompt"])
    tools = list(cast(list[str], spec.get("tools", [])))
    permissions = list(cast(list[str], spec.get("permissions", [])))
    tags = list(cast(list[str], spec.get("tags", [])))
    description = str(spec.get("description", ""))
    notes = str(spec.get("notes", ""))
    created_at = datetime.now(tz=UTC).isoformat()

    registry._conn.execute(
        "INSERT INTO agents "
        "(id, name, parent_id, system_prompt, tools, permissions, "
        " working_dir, source, created_at, description, tags, "
        " usage_count, failure_count, last_used, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            agent_id,
            name,
            None,
            system_prompt,
            json.dumps(tools),
            json.dumps(permissions),
            "",
            "catalog",
            created_at,
            description,
            json.dumps(tags),
            0,
            0,
            "",
            notes,
        ),
    )
    registry._conn.commit()


def _update_catalog_agent(
    registry: RegistryAPI,
    agent_id: str,
    new_system_prompt: str,
) -> None:
    """Overwrite the ``system_prompt`` of an existing catalog agent in-place.

    Base agents are the only records mutated in-place; user agents always
    clone-on-modify to preserve provenance.

    Args:
        registry: Open registry instance.
        agent_id: Deterministic ID of the catalog agent to update.
        new_system_prompt: Replacement system prompt text.
    """
    registry._conn.execute(
        "UPDATE agents SET system_prompt = ? WHERE id = ?",
        (new_system_prompt, agent_id),
    )
    registry._conn.commit()


def _flag_clones(
    registry: RegistryAPI,
    base_agent_id: str,
    base_agent_name: str,
) -> None:
    """Append a ``[PARENT UPDATED]`` notice to every direct clone of a base agent.

    Only direct children (``parent_id = base_agent_id``) are flagged.  Deeper
    descendants will see the notice on their own parent when they inspect it.

    Args:
        registry: Open registry instance.
        base_agent_id: ID of the updated catalog base agent.
        base_agent_name: Human-readable name used in the notice text.
    """
    notice = (
        f"{_PARENT_UPDATED_PREFIX} The base agent '{base_agent_name}' was updated. "
        "Review changes."
    )

    # Fetch all direct clones
    cur = registry._conn.execute(
        "SELECT id, notes FROM agents WHERE parent_id = ?",
        (base_agent_id,),
    )
    rows = cur.fetchall()

    for clone_id, existing_notes in rows:
        # Guard: do not append the same notice twice if seed runs again
        # before the user acknowledges it.
        if notice in (existing_notes or ""):
            continue
        separator = "\n" if existing_notes else ""
        updated_notes = f"{existing_notes}{separator}{notice}"
        registry._conn.execute(
            "UPDATE agents SET notes = ? WHERE id = ?",
            (updated_notes, clone_id),
        )

    registry._conn.commit()


def get_default_registry() -> RegistryAPI:
    """Return a :class:`RegistryAPI` pointed at the default database path.

    Convenience function for CLI commands that need a registry without
    caring about the catalog seeding logic.

    Returns:
        An open :class:`RegistryAPI` instance.
    """
    config = load_config()
    return RegistryAPI(config.base_dir / "registry.db")
