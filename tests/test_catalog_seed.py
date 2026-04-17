"""Tests for swarm.catalog.seed — seed_base_agents() idempotency and update logic."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.catalog.seed import (
    _PARENT_UPDATED_PREFIX,
    _catalog_id,
    seed_base_agents,
)
from swarm.registry.api import RegistryAPI

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> Iterator[RegistryAPI]:
    """Return an isolated registry backed by a tmp_path database."""
    api = RegistryAPI(tmp_path / "registry.db")
    try:
        yield api
    finally:
        api.close()


_MINIMAL_CATALOG: list[dict[str, object]] = [
    {
        "name": "alpha-agent",
        "description": "Alpha description.",
        "tags": ["base", "technical", "test"],
        "tools": ["Read", "Grep"],
        "permissions": [],
        "notes": "Alpha notes.",
        "system_prompt": "You are alpha.",
        "model": "sonnet",
    },
    {
        "name": "beta-agent",
        "description": "Beta description.",
        "tags": ["base", "general", "test"],
        "tools": ["Write"],
        "permissions": [],
        "notes": "",
        "system_prompt": "You are beta.",
        "model": "haiku",
    },
]

_UPDATED_CATALOG: list[dict[str, object]] = [
    {**_MINIMAL_CATALOG[0], "system_prompt": "You are alpha v2."},
    _MINIMAL_CATALOG[1],
]


# ---------------------------------------------------------------------------
# _catalog_id
# ---------------------------------------------------------------------------


class TestCatalogId:
    def test_returns_valid_uuid(self) -> None:
        result = _catalog_id("code-researcher")
        parsed = uuid.UUID(result)
        assert parsed.version == 5

    def test_deterministic(self) -> None:
        assert _catalog_id("code-researcher") == _catalog_id("code-researcher")

    def test_different_names_differ(self) -> None:
        assert _catalog_id("alpha") != _catalog_id("beta")

    def test_uses_swarm_catalog_prefix(self) -> None:
        # The UUID must be consistent with the documented formula.
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "swarm-catalog-my-agent"))
        assert _catalog_id("my-agent") == expected


# ---------------------------------------------------------------------------
# seed_base_agents — first run (create)
# ---------------------------------------------------------------------------


class TestSeedCreate:
    def test_creates_all_catalog_agents(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            summary = seed_base_agents(registry)

        assert set(summary["created"]) == {"alpha-agent", "beta-agent"}
        assert summary["updated"] == []
        assert summary["unchanged"] == []

    def test_agents_have_catalog_source(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(_catalog_id("alpha-agent"))
        assert agent is not None
        assert agent.source == "catalog"

    def test_agents_have_deterministic_ids(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(_catalog_id("alpha-agent"))
        assert agent is not None
        assert agent.id == _catalog_id("alpha-agent")

    def test_agents_store_correct_fields(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(_catalog_id("alpha-agent"))
        assert agent is not None
        assert agent.name == "alpha-agent"
        assert agent.system_prompt == "You are alpha."
        assert agent.description == "Alpha description."
        assert "Read" in agent.tools
        assert "Grep" in agent.tools
        assert "technical" in agent.tags
        assert agent.notes == "Alpha notes."

    def test_agents_have_no_parent(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(_catalog_id("alpha-agent"))
        assert agent is not None
        assert agent.parent_id is None


# ---------------------------------------------------------------------------
# seed_base_agents — idempotency (unchanged)
# ---------------------------------------------------------------------------


class TestSeedIdempotency:
    def test_second_run_reports_unchanged(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)
            summary = seed_base_agents(registry)

        assert summary["created"] == []
        assert summary["updated"] == []
        assert set(summary["unchanged"]) == {"alpha-agent", "beta-agent"}

    def test_many_runs_do_not_duplicate(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            for _ in range(5):
                seed_base_agents(registry)

        agents = [a for a in registry.list_agents() if a.source == "catalog"]
        names = [a.name for a in agents]
        assert len(names) == len(set(names)), "Duplicate catalog agents detected"

    def test_second_run_does_not_change_agent(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)
            before = registry.get(_catalog_id("alpha-agent"))
            seed_base_agents(registry)
            after = registry.get(_catalog_id("alpha-agent"))

        assert before is not None and after is not None
        assert before.system_prompt == after.system_prompt
        assert before.created_at == after.created_at


# ---------------------------------------------------------------------------
# seed_base_agents — update path
# ---------------------------------------------------------------------------


class TestSeedUpdate:
    def test_update_reports_agent_name(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            summary = seed_base_agents(registry)

        assert "alpha-agent" in summary["updated"]
        assert "beta-agent" in summary["unchanged"]

    def test_update_overwrites_system_prompt(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(_catalog_id("alpha-agent"))
        assert agent is not None
        assert agent.system_prompt == "You are alpha v2."

    def test_update_preserves_agent_id(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)
            original_id = _catalog_id("alpha-agent")

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        agent = registry.get(original_id)
        assert agent is not None  # same row, same ID

    def test_unchanged_agent_not_in_updated(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            summary = seed_base_agents(registry)

        assert "beta-agent" not in summary["updated"]


# ---------------------------------------------------------------------------
# seed_base_agents — clone flagging
# ---------------------------------------------------------------------------


class TestCloneFlagging:
    def _seed_and_clone(self, registry: RegistryAPI) -> str:
        """Seed the minimal catalog and clone alpha-agent. Returns clone ID."""
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("alpha-agent")
        clone = registry.clone(base_id, {"name": "my-alpha"})
        return clone.id

    def test_clone_receives_parent_updated_notice(self, registry: RegistryAPI) -> None:
        clone_id = self._seed_and_clone(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        clone = registry.get(clone_id)
        assert clone is not None
        assert _PARENT_UPDATED_PREFIX in clone.notes

    def test_notice_contains_agent_name(self, registry: RegistryAPI) -> None:
        clone_id = self._seed_and_clone(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        clone = registry.get(clone_id)
        assert clone is not None
        assert "alpha-agent" in clone.notes

    def test_notice_not_duplicated_on_repeated_update(self, registry: RegistryAPI) -> None:
        clone_id = self._seed_and_clone(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)
            seed_base_agents(registry)

        clone = registry.get(clone_id)
        assert clone is not None
        count = clone.notes.count(_PARENT_UPDATED_PREFIX)
        assert count == 1, f"Notice appended {count} times, expected 1"

    def test_unchanged_base_clones_not_flagged(self, registry: RegistryAPI) -> None:
        """Clones of beta-agent (unchanged) must NOT get a notice."""
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        beta_id = _catalog_id("beta-agent")
        clone = registry.clone(beta_id, {"name": "my-beta"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        refreshed = registry.get(clone.id)
        assert refreshed is not None
        assert _PARENT_UPDATED_PREFIX not in (refreshed.notes or "")

    def test_clone_with_existing_notes_preserves_them(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("alpha-agent")
        clone = registry.clone(base_id, {"name": "noted-alpha", "notes": "My existing note."})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        refreshed = registry.get(clone.id)
        assert refreshed is not None
        assert "My existing note." in refreshed.notes
        assert _PARENT_UPDATED_PREFIX in refreshed.notes

    def test_only_direct_clones_are_flagged(self, registry: RegistryAPI) -> None:
        """Grandchild clones (parent_id -> clone, not base) must not be flagged."""
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("alpha-agent")
        child = registry.clone(base_id, {"name": "child-alpha"})
        grandchild = registry.clone(child.id, {"name": "grandchild-alpha"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _UPDATED_CATALOG):
            seed_base_agents(registry)

        gc = registry.get(grandchild.id)
        assert gc is not None
        # Grandchild's parent is `child`, not the base catalog agent — no flag.
        assert _PARENT_UPDATED_PREFIX not in (gc.notes or "")


# ---------------------------------------------------------------------------
# seed_base_agents — default registry construction
# ---------------------------------------------------------------------------


class TestSeedDefaultRegistry:
    def test_creates_registry_from_config(self, tmp_path: Path) -> None:
        """When no registry is passed, seed_base_agents creates one from config."""
        from swarm.config import SwarmConfig

        config = SwarmConfig(base_dir=tmp_path / ".swarm")
        config.base_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch("swarm.catalog.seed.ALL_BASE_AGENTS", _MINIMAL_CATALOG),
            patch("swarm.catalog.seed.load_config", return_value=config),
        ):
            summary = seed_base_agents()  # no registry arg

        assert set(summary["created"]) == {"alpha-agent", "beta-agent"}


# ---------------------------------------------------------------------------
# Integration — real catalog
# ---------------------------------------------------------------------------


class TestRealCatalogIntegration:
    def test_real_catalog_seeds_without_error(self, registry: RegistryAPI) -> None:
        """Smoke-test that ALL_BASE_AGENTS can be seeded without exception."""
        summary = seed_base_agents(registry)
        total = len(summary["created"]) + len(summary["updated"]) + len(summary["unchanged"])
        # The catalog declares 66 agents; verify we seeded a substantial number.
        assert total >= 60

    def test_real_catalog_all_have_catalog_source(self, registry: RegistryAPI) -> None:
        seed_base_agents(registry)
        catalog_agents = [a for a in registry.list_agents() if a.source == "catalog"]
        assert len(catalog_agents) >= 60
        for agent in catalog_agents:
            assert agent.source == "catalog"

    def test_real_catalog_ids_are_stable(self, registry: RegistryAPI) -> None:
        """IDs must match the deterministic formula, not random UUIDs."""
        from swarm.catalog import ALL_BASE_AGENTS

        seed_base_agents(registry)
        for spec in ALL_BASE_AGENTS:
            name = str(spec["name"])
            expected_id = _catalog_id(name)
            agent = registry.get(expected_id)
            assert agent is not None, f"Agent '{name}' not found at deterministic ID"
            assert agent.id == expected_id
