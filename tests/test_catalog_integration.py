"""End-to-end integration tests for the Swarm base agent catalog specialization workflow.

Tests cover seeding, discovery, cloning, parent-update flagging, template completeness,
and catalog structural validity.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.catalog import ALL_BASE_AGENTS
from swarm.catalog.seed import (
    _PARENT_UPDATED_PREFIX,
    _catalog_id,
    seed_base_agents,
)
from swarm.plan.templates import BUILTIN_TEMPLATES_DIR
from swarm.registry.api import RegistryAPI


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> RegistryAPI:
    """Return an isolated registry backed by a tmp_path database."""
    return RegistryAPI(tmp_path / "registry.db")


@pytest.fixture()
def seeded_registry(tmp_path: Path) -> RegistryAPI:
    """Return a registry with the full real catalog already seeded."""
    reg = RegistryAPI(tmp_path / "seeded.db")
    seed_base_agents(reg)
    return reg


# ---------------------------------------------------------------------------
# 1. Seed then discover
# ---------------------------------------------------------------------------


class TestSeedThenDiscover:
    """Seed base agents, then verify search finds them and source is 'catalog'."""

    def test_search_by_name_finds_catalog_agent(self, seeded_registry: RegistryAPI) -> None:
        results = seeded_registry.search("code-reviewer")
        names = [a.name for a in results]
        assert "code-reviewer" in names

    def test_search_by_description_fragment_finds_catalog_agent(
        self, seeded_registry: RegistryAPI
    ) -> None:
        # architect's description contains "Designs system structure"
        results = seeded_registry.search("Designs system structure")
        names = [a.name for a in results]
        assert "architect" in names

    def test_search_by_tag_finds_catalog_agents(self, seeded_registry: RegistryAPI) -> None:
        # All base agents share the "base" tag; searching for it returns many
        results = seeded_registry.search("base")
        assert len(results) >= 60

    def test_catalog_source_distinguishes_base_agents(
        self, seeded_registry: RegistryAPI
    ) -> None:
        # Add a user agent to the registry
        seeded_registry.create("user-agent", "A custom agent.", [], [])

        catalog_agents = [a for a in seeded_registry.list_agents() if a.source == "catalog"]
        user_agents = [a for a in seeded_registry.list_agents() if a.source == "forge"]

        assert len(catalog_agents) == 66
        assert len(user_agents) == 1
        assert all(a.source == "catalog" for a in catalog_agents)
        assert all(a.source == "forge" for a in user_agents)

    def test_search_returns_only_catalog_source_when_no_user_agents(
        self, seeded_registry: RegistryAPI
    ) -> None:
        results = seeded_registry.search("reviewer")
        for agent in results:
            assert agent.source == "catalog"

    def test_search_by_prompt_keyword_finds_agent(self, seeded_registry: RegistryAPI) -> None:
        # All agents have [DOMAIN-SPECIFIC: in their system_prompt
        results = seeded_registry.search("DOMAIN-SPECIFIC")
        assert len(results) == 66

    def test_resolve_by_exact_name_finds_catalog_agent(
        self, seeded_registry: RegistryAPI
    ) -> None:
        agent = seeded_registry.resolve_agent("implementer")
        assert agent.name == "implementer"
        assert agent.source == "catalog"


# ---------------------------------------------------------------------------
# 2. Clone specialization workflow
# ---------------------------------------------------------------------------


class TestCloneSpecializationWorkflow:
    """Clone a base agent and verify provenance, source, and prompt overrides."""

    def test_clone_code_reviewer_has_correct_parent_id(
        self, seeded_registry: RegistryAPI
    ) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(
            base.id,
            {
                "name": "python-reviewer",
                "system_prompt": (
                    base.system_prompt
                    + "\n\n[PYTHON-SPECIFIC: Focus on PEP 8, type hints, and pytest patterns.]"
                ),
            },
        )
        assert clone.parent_id == base.id

    def test_clone_code_reviewer_source_is_catalog(
        self, seeded_registry: RegistryAPI
    ) -> None:
        """Clone inherits the source of the original ('catalog')."""
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(
            base.id, {"name": "python-reviewer", "system_prompt": "custom prompt"}
        )
        # Clone inherits original's source (see RegistryAPI.clone implementation)
        assert clone.source == "catalog"

    def test_clone_code_reviewer_has_specialized_prompt(
        self, seeded_registry: RegistryAPI
    ) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        specialized = (
            base.system_prompt
            + "\n\n[PYTHON-SPECIFIC: Enforce strict mypy and black compliance.]"
        )
        clone = seeded_registry.clone(
            base.id,
            {"name": "python-reviewer", "system_prompt": specialized},
        )
        assert "mypy" in clone.system_prompt
        assert "black" in clone.system_prompt

    def test_clone_has_different_id_from_base(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(base.id, {"name": "python-reviewer"})
        assert clone.id != base.id

    def test_clone_name_override_applied(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(base.id, {"name": "python-reviewer"})
        assert clone.name == "python-reviewer"

    def test_clone_base_prompt_retained_when_not_overridden(
        self, seeded_registry: RegistryAPI
    ) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(base.id, {"name": "python-reviewer"})
        assert clone.system_prompt == base.system_prompt

    def test_clone_is_retrievable_by_id(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("code-reviewer")
        clone = seeded_registry.clone(base.id, {"name": "python-reviewer"})
        retrieved = seeded_registry.get(clone.id)
        assert retrieved is not None
        assert retrieved.name == "python-reviewer"


# ---------------------------------------------------------------------------
# 3. Clone preserves base structure
# ---------------------------------------------------------------------------


class TestClonePreservesBaseStructure:
    """Clone 'architect' into 'api-architect'; verify specialization and base content."""

    def test_api_architect_clone_contains_specialization(
        self, seeded_registry: RegistryAPI
    ) -> None:
        base = seeded_registry.resolve_agent("architect")
        api_suffix = "\n\n[API-SPECIFIC: Focus on REST, OpenAPI specs, and versioning.]"
        clone = seeded_registry.clone(
            base.id,
            {"name": "api-architect", "system_prompt": base.system_prompt + api_suffix},
        )
        assert "REST" in clone.system_prompt
        assert "OpenAPI" in clone.system_prompt

    def test_api_architect_clone_retains_base_methodology(
        self, seeded_registry: RegistryAPI
    ) -> None:
        """The base architect prompt text is preserved inside the cloned prompt."""
        base = seeded_registry.resolve_agent("architect")
        api_suffix = "\n\n[API-SPECIFIC: Focus on REST, OpenAPI specs, and versioning.]"
        clone = seeded_registry.clone(
            base.id,
            {"name": "api-architect", "system_prompt": base.system_prompt + api_suffix},
        )
        # The core base methodology must still be present
        assert base.system_prompt in clone.system_prompt

    def test_api_architect_clone_parent_id_points_to_base(
        self, seeded_registry: RegistryAPI
    ) -> None:
        base = seeded_registry.resolve_agent("architect")
        clone = seeded_registry.clone(base.id, {"name": "api-architect"})
        assert clone.parent_id == base.id
        assert clone.parent_id == _catalog_id("architect")

    def test_clone_preserves_base_tools(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("architect")
        clone = seeded_registry.clone(base.id, {"name": "api-architect"})
        assert clone.tools == base.tools

    def test_clone_preserves_base_tags(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("architect")
        clone = seeded_registry.clone(base.id, {"name": "api-architect"})
        assert clone.tags == base.tags

    def test_clone_resets_usage_count(self, seeded_registry: RegistryAPI) -> None:
        base = seeded_registry.resolve_agent("architect")
        clone = seeded_registry.clone(base.id, {"name": "api-architect"})
        assert clone.usage_count == 0
        assert clone.failure_count == 0


# ---------------------------------------------------------------------------
# 4. Parent-update flagging end-to-end
# ---------------------------------------------------------------------------

_IMPLEMENTER_MINIMAL: list[dict[str, object]] = [
    {
        "name": "implementer",
        "description": "Writes production-quality code from specifications.",
        "tags": ["base", "technical", "implementation"],
        "tools": ["Read", "Write", "Edit"],
        "permissions": [],
        "notes": "",
        "system_prompt": "You are an implementer. [DOMAIN-SPECIFIC: Add details here.]",
        "model": "sonnet",
    }
]

_IMPLEMENTER_UPDATED: list[dict[str, object]] = [
    {
        **_IMPLEMENTER_MINIMAL[0],
        "system_prompt": (
            "You are an implementer v2. [DOMAIN-SPECIFIC: Add details here.]"
        ),
    }
]


class TestParentUpdateFlaggingEndToEnd:
    """Re-seeding with a changed catalog flags all direct clones of the changed agent."""

    def test_re_seed_with_updated_prompt_flags_clone_notes(
        self, registry: RegistryAPI
    ) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_MINIMAL):
            seed_base_agents(registry)

        base_id = _catalog_id("implementer")
        clone = registry.clone(base_id, {"name": "python-implementer"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_UPDATED):
            seed_base_agents(registry)

        refreshed = registry.get(clone.id)
        assert refreshed is not None
        assert _PARENT_UPDATED_PREFIX in refreshed.notes

    def test_flagged_notes_contains_base_agent_name(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_MINIMAL):
            seed_base_agents(registry)

        base_id = _catalog_id("implementer")
        clone = registry.clone(base_id, {"name": "python-implementer"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_UPDATED):
            seed_base_agents(registry)

        refreshed = registry.get(clone.id)
        assert refreshed is not None
        assert "implementer" in refreshed.notes

    def test_base_agent_prompt_is_updated_after_re_seed(
        self, registry: RegistryAPI
    ) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_MINIMAL):
            seed_base_agents(registry)

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_UPDATED):
            seed_base_agents(registry)

        base = registry.get(_catalog_id("implementer"))
        assert base is not None
        assert "v2" in base.system_prompt

    def test_flag_not_duplicated_on_repeated_re_seed(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_MINIMAL):
            seed_base_agents(registry)

        base_id = _catalog_id("implementer")
        clone = registry.clone(base_id, {"name": "python-implementer"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_UPDATED):
            seed_base_agents(registry)
            seed_base_agents(registry)

        refreshed = registry.get(clone.id)
        assert refreshed is not None
        count = refreshed.notes.count(_PARENT_UPDATED_PREFIX)
        assert count == 1

    def test_unchanged_clone_is_not_flagged(self, registry: RegistryAPI) -> None:
        """A clone whose base did not change must not receive the notice."""
        extra_agent: list[dict[str, object]] = [
            {
                "name": "extra-agent",
                "description": "Stable base agent.",
                "tags": ["base"],
                "tools": [],
                "permissions": [],
                "notes": "",
                "system_prompt": "Stable. [DOMAIN-SPECIFIC: details.]",
                "model": "haiku",
            }
        ]
        combined = _IMPLEMENTER_MINIMAL + extra_agent
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", combined):
            seed_base_agents(registry)

        extra_base_id = _catalog_id("extra-agent")
        stable_clone = registry.clone(extra_base_id, {"name": "stable-clone"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _IMPLEMENTER_UPDATED + extra_agent):
            seed_base_agents(registry)

        refreshed = registry.get(stable_clone.id)
        assert refreshed is not None
        assert _PARENT_UPDATED_PREFIX not in (refreshed.notes or "")


# ---------------------------------------------------------------------------
# 5. Multiple clones from same base
# ---------------------------------------------------------------------------

_TEST_WRITER_CATALOG: list[dict[str, object]] = [
    {
        "name": "test-writer",
        "description": "Creates comprehensive test suites.",
        "tags": ["base", "technical", "testing"],
        "tools": ["Read", "Write", "Edit"],
        "permissions": [],
        "notes": "",
        "system_prompt": "You are a test writer. [DOMAIN-SPECIFIC: Add framework details.]",
        "model": "sonnet",
    }
]

_TEST_WRITER_UPDATED: list[dict[str, object]] = [
    {
        **_TEST_WRITER_CATALOG[0],
        "system_prompt": (
            "You are a test writer v2. [DOMAIN-SPECIFIC: Add framework details.]"
        ),
    }
]


class TestMultipleClonesFromSameBase:
    """Multiple clones from one base all share parent_id and get flagged on update."""

    def test_two_clones_have_same_parent_id(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("test-writer")
        pytest_writer = registry.clone(base_id, {"name": "pytest-writer"})
        playwright_writer = registry.clone(base_id, {"name": "playwright-writer"})

        assert pytest_writer.parent_id == base_id
        assert playwright_writer.parent_id == base_id

    def test_two_clones_have_different_ids(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("test-writer")
        pytest_writer = registry.clone(base_id, {"name": "pytest-writer"})
        playwright_writer = registry.clone(base_id, {"name": "playwright-writer"})

        assert pytest_writer.id != playwright_writer.id

    def test_both_clones_independently_searchable(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("test-writer")
        registry.clone(base_id, {"name": "pytest-writer"})
        registry.clone(base_id, {"name": "playwright-writer"})

        pytest_results = registry.search("pytest-writer")
        playwright_results = registry.search("playwright-writer")

        assert len(pytest_results) == 1
        assert pytest_results[0].name == "pytest-writer"
        assert len(playwright_results) == 1
        assert playwright_results[0].name == "playwright-writer"

    def test_base_update_flags_both_clones(self, registry: RegistryAPI) -> None:
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("test-writer")
        pytest_writer = registry.clone(base_id, {"name": "pytest-writer"})
        playwright_writer = registry.clone(base_id, {"name": "playwright-writer"})

        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_UPDATED):
            seed_base_agents(registry)

        for clone_id, label in [
            (pytest_writer.id, "pytest-writer"),
            (playwright_writer.id, "playwright-writer"),
        ]:
            refreshed = registry.get(clone_id)
            assert refreshed is not None, f"{label} not found after re-seed"
            assert _PARENT_UPDATED_PREFIX in refreshed.notes, (
                f"{label} was not flagged after base agent update"
            )

    def test_clone_notes_are_independent(self, registry: RegistryAPI) -> None:
        """Notes prepopulated on one clone must not appear on the other."""
        with patch("swarm.catalog.seed.ALL_BASE_AGENTS", _TEST_WRITER_CATALOG):
            seed_base_agents(registry)

        base_id = _catalog_id("test-writer")
        registry.clone(base_id, {"name": "pytest-writer", "notes": "pytest-specific note"})
        playwright_writer = registry.clone(base_id, {"name": "playwright-writer"})

        refreshed = registry.get(playwright_writer.id)
        assert refreshed is not None
        assert "pytest-specific note" not in (refreshed.notes or "")


# ---------------------------------------------------------------------------
# 6. Full template resolution
# ---------------------------------------------------------------------------


class TestFullTemplateResolution:
    """Every agent_type referenced in the 6 builtin plan templates must exist in the registry."""

    def _collect_agent_types_from_template(self, json_path: Path) -> list[str]:
        """Return all distinct non-empty agent_type values from a template JSON file."""
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return [
            step["agent_type"]
            for step in data.get("steps", [])
            if step.get("agent_type")
        ]

    def test_twelve_builtin_templates_exist(self) -> None:
        templates = list(BUILTIN_TEMPLATES_DIR.glob("*.json"))
        assert len(templates) == 12, (
            f"Expected 12 builtin templates, found {len(templates)}: "
            + ", ".join(t.name for t in templates)
        )

    def test_code_review_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "code-review.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        assert agent_types, "code-review template has no agent_type entries"
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"code-review template references '{agent_type}' which is not in the catalog"
            )

    def test_feature_build_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "feature-build.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"feature-build template references '{agent_type}' not found in catalog"
            )

    def test_security_audit_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "security-audit.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"security-audit template references '{agent_type}' not found in catalog"
            )

    def test_business_plan_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "business-plan.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"business-plan template references '{agent_type}' not found in catalog"
            )

    def test_hiring_pipeline_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "hiring-pipeline.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"hiring-pipeline template references '{agent_type}' not found in catalog"
            )

    def test_product_launch_template_agent_types_in_registry(
        self, seeded_registry: RegistryAPI
    ) -> None:
        template_path = BUILTIN_TEMPLATES_DIR / "product-launch.json"
        agent_types = self._collect_agent_types_from_template(template_path)
        for agent_type in agent_types:
            result = seeded_registry.search(agent_type)
            names = [a.name for a in result]
            assert agent_type in names, (
                f"product-launch template references '{agent_type}' not found in catalog"
            )

    def test_all_templates_all_agent_types_present(self, seeded_registry: RegistryAPI) -> None:
        """Parametric sweep: every agent_type across all 12 templates is in the registry."""
        catalog_names = {a.name for a in seeded_registry.list_agents() if a.source == "catalog"}
        missing: list[str] = []

        for template_path in BUILTIN_TEMPLATES_DIR.glob("*.json"):
            agent_types = self._collect_agent_types_from_template(template_path)
            for agent_type in agent_types:
                if agent_type not in catalog_names:
                    missing.append(f"{template_path.stem}::{agent_type}")

        assert not missing, (
            f"Template agent_types not found in catalog:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# 7. Catalog completeness
# ---------------------------------------------------------------------------


class TestCatalogCompleteness:
    """Structural validation of ALL_BASE_AGENTS against documented requirements."""

    _VALID_MODELS = frozenset({"haiku", "sonnet", "opus"})

    def test_exactly_66_base_agents_load(self) -> None:
        assert len(ALL_BASE_AGENTS) == 66

    def test_all_agents_have_non_empty_description(self) -> None:
        empty = [a["name"] for a in ALL_BASE_AGENTS if not str(a.get("description", "")).strip()]
        assert not empty, f"Agents with empty description: {empty}"

    def test_all_agents_have_base_in_tags(self) -> None:
        missing = [
            a["name"]
            for a in ALL_BASE_AGENTS
            if "base" not in list(a.get("tags", []))
        ]
        assert not missing, f"Agents missing 'base' tag: {missing}"

    def test_all_agents_have_valid_model(self) -> None:
        invalid = [
            f"{a['name']}={a.get('model')!r}"
            for a in ALL_BASE_AGENTS
            if str(a.get("model", "")) not in self._VALID_MODELS
        ]
        assert not invalid, f"Agents with invalid model: {invalid}"

    def test_all_agents_have_domain_specific_hook(self) -> None:
        missing = [
            a["name"]
            for a in ALL_BASE_AGENTS
            if "[DOMAIN-SPECIFIC:" not in str(a.get("system_prompt", ""))
        ]
        assert not missing, f"Agents missing [DOMAIN-SPECIFIC: hook: {missing}"

    def test_all_agents_have_non_empty_system_prompt(self) -> None:
        empty = [a["name"] for a in ALL_BASE_AGENTS if not str(a.get("system_prompt", "")).strip()]
        assert not empty, f"Agents with empty system_prompt: {empty}"

    def test_all_agents_have_non_empty_name(self) -> None:
        empty = [a for a in ALL_BASE_AGENTS if not str(a.get("name", "")).strip()]
        assert not empty, "One or more agents have an empty name"

    def test_66_agents_seed_into_registry(self, registry: RegistryAPI) -> None:
        summary = seed_base_agents(registry)
        total = len(summary["created"]) + len(summary["updated"]) + len(summary["unchanged"])
        assert total == 66

    def test_all_seeded_agents_have_catalog_source(self, registry: RegistryAPI) -> None:
        seed_base_agents(registry)
        catalog_agents = [a for a in registry.list_agents() if a.source == "catalog"]
        assert len(catalog_agents) == 66


# ---------------------------------------------------------------------------
# 8. No duplicate names in catalog
# ---------------------------------------------------------------------------


class TestNoDuplicateNamesInCatalog:
    """All 66 catalog entries must have unique names."""

    def test_all_names_are_unique(self) -> None:
        names = [str(a["name"]) for a in ALL_BASE_AGENTS]
        duplicates = [n for n in set(names) if names.count(n) > 1]
        assert not duplicates, f"Duplicate agent names in catalog: {duplicates}"

    def test_unique_names_equal_total_count(self) -> None:
        names = [str(a["name"]) for a in ALL_BASE_AGENTS]
        assert len(names) == len(set(names))

    def test_seeded_names_are_unique_in_registry(self, registry: RegistryAPI) -> None:
        seed_base_agents(registry)
        catalog_agents = [a for a in registry.list_agents() if a.source == "catalog"]
        names = [a.name for a in catalog_agents]
        duplicates = [n for n in set(names) if names.count(n) > 1]
        assert not duplicates, f"Duplicate names in seeded registry: {duplicates}"

    def test_deterministic_ids_are_unique(self) -> None:
        """Each unique name maps to a unique deterministic ID."""
        ids = [_catalog_id(str(a["name"])) for a in ALL_BASE_AGENTS]
        assert len(ids) == len(set(ids)), "Deterministic ID collision detected"
