"""Tests for swarm.mcp.forge_tools."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.forge.api import ForgeAPI
from swarm.forge.frontmatter import parse_frontmatter
from swarm.mcp import state
from swarm.mcp.forge_tools import (
    forge_clone,
    forge_create,
    forge_export_subagent,
    forge_get,
    forge_import_subagents,
    forge_list,
    forge_remove,
    forge_suggest,
)
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> Iterator[None]:
    state.registry_api = RegistryAPI(tmp_path / "registry.db")
    state.forge_api = ForgeAPI(tmp_path / "registry.db", tmp_path / "forge")
    try:
        yield
    finally:
        assert state.registry_api is not None
        state.registry_api.close()
        assert state.forge_api is not None
        state.forge_api.close()
        state.registry_api = None
        state.forge_api = None


class TestForgeList:
    def test_empty(self) -> None:
        result = json.loads(forge_list())
        assert result == []

    def test_lists_all(self) -> None:
        forge_create("a", "prompt a")
        forge_create("b", "prompt b")
        result = json.loads(forge_list())
        assert len(result) == 2

    def test_filters_by_name(self) -> None:
        forge_create("code-reviewer", "Reviews code.")
        forge_create("writer", "Writes docs.")
        result = json.loads(forge_list("review"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"


class TestForgeGet:
    def test_get_by_id(self) -> None:
        created = json.loads(forge_create("agent", "prompt"))
        result = json.loads(forge_get(agent_id=created["id"]))
        assert result["name"] == "agent"

    def test_get_by_name(self) -> None:
        forge_create("named-agent", "prompt")
        result = json.loads(forge_get(name="named-agent"))
        assert result["name"] == "named-agent"

    def test_not_found(self) -> None:
        result = json.loads(forge_get(agent_id="nonexistent"))
        assert "error" in result

    def test_no_params(self) -> None:
        result = json.loads(forge_get())
        assert "error" in result


class TestForgeCreate:
    def test_creates_agent(self) -> None:
        result = json.loads(forge_create("reviewer", "Reviews code.", '["Read"]', '["read"]'))
        assert result["name"] == "reviewer"
        assert result["id"]
        assert result["tools"] == ["Read"]
        assert result["permissions"] == ["read"]

    def test_default_tools_and_permissions(self) -> None:
        result = json.loads(forge_create("simple", "Does stuff."))
        assert result["tools"] == []
        assert result["permissions"] == []


class TestForgeClone:
    def test_clones_with_overrides(self) -> None:
        original = json.loads(forge_create("base", "Base prompt.", '["Read"]', '[]'))
        cloned = json.loads(forge_clone(original["id"], name="derived", system_prompt="New prompt."))
        assert cloned["name"] == "derived"
        assert cloned["system_prompt"] == "New prompt."
        assert cloned["parent_id"] == original["id"]

    def test_clone_keeps_original_when_no_override(self) -> None:
        original = json.loads(forge_create("base", "Base prompt.", '["Read"]', '["write"]'))
        cloned = json.loads(forge_clone(original["id"], name="copy"))
        assert cloned["tools"] == ["Read"]
        assert cloned["permissions"] == ["write"]


class TestForgeCloneByName:
    def test_clone_by_source_name(self) -> None:
        forge_create("base-agent", "Base prompt.", '["Read"]', '[]')
        cloned = json.loads(forge_clone(source_name="base-agent", name="derived"))
        assert cloned["name"] == "derived"
        assert cloned["system_prompt"] == "Base prompt."

    def test_clone_no_source(self) -> None:
        result = json.loads(forge_clone())
        assert "error" in result


class TestForgeSuggest:
    def test_finds_matching(self) -> None:
        forge_create("code-reviewer", "Reviews code quality.")
        forge_create("writer", "Writes documents.")
        result = json.loads(forge_suggest("review"))
        assert len(result) == 1
        assert result[0]["name"] == "code-reviewer"

    def test_no_match(self) -> None:
        result = json.loads(forge_suggest("zzzzz"))
        assert result == []


class TestForgeRemove:
    def test_removes_existing(self) -> None:
        created = json.loads(forge_create("temp", "prompt"))
        result = json.loads(forge_remove(created["id"]))
        assert result["ok"] is True

    def test_returns_false_for_missing(self) -> None:
        result = json.loads(forge_remove("nonexistent"))
        assert result["ok"] is False


class TestForgeCreateWithDescriptionAndTags:
    def test_forge_create_with_description_and_tags(self) -> None:
        result = json.loads(
            forge_create(
                "py-reviewer",
                "Reviews Python code.",
                description="Checks Python style and correctness",
                tags='["python", "review"]',
            )
        )
        assert result["description"] == "Checks Python style and correctness"
        assert result["tags"] == ["python", "review"]

    def test_forge_list_truncates_system_prompt(self) -> None:
        long_prompt = "A" * 120
        forge_create("verbose-agent", long_prompt)
        result = json.loads(forge_list())
        agent = next(r for r in result if r["name"] == "verbose-agent")
        assert agent["system_prompt"] == "A" * 80 + "..."

    def test_forge_list_includes_description_and_tags(self) -> None:
        forge_create(
            "tagged-agent",
            "Does tagged things.",
            description="An agent with tags",
            tags='["alpha", "beta"]',
        )
        result = json.loads(forge_list())
        agent = next(r for r in result if r["name"] == "tagged-agent")
        assert agent["description"] == "An agent with tags"
        assert agent["tags"] == ["alpha", "beta"]

    def test_forge_clone_with_description_override(self) -> None:
        original = json.loads(
            forge_create(
                "original-agent",
                "Original prompt.",
                description="Original description",
            )
        )
        cloned = json.loads(
            forge_clone(
                original["id"],
                name="cloned-agent",
                description="Cloned description",
            )
        )
        assert cloned["description"] == "Cloned description"
        assert cloned["parent_id"] == original["id"]


class TestForgeCreateWithPerformanceMetadata:
    def test_forge_create_with_notes(self) -> None:
        result = json.loads(
            forge_create("noted-agent", "Does stuff.", notes="Watch for rate limits")
        )
        assert result["notes"] == "Watch for rate limits"
        assert result["usage_count"] == 0
        assert result["failure_count"] == 0
        assert result["last_used"] == ""

    def test_forge_create_defaults_zero_counts(self) -> None:
        result = json.loads(forge_create("plain-agent", "Does things."))
        assert result["usage_count"] == 0
        assert result["failure_count"] == 0
        assert result["notes"] == ""

    def test_forge_list_includes_usage_and_failure_counts(self) -> None:
        forge_create("tracked-agent", "Does tracked things.", notes="note")
        result = json.loads(forge_list())
        agent = next(r for r in result if r["name"] == "tracked-agent")
        assert "usage_count" in agent
        assert "failure_count" in agent
        assert agent["usage_count"] == 0
        assert agent["failure_count"] == 0

    def test_forge_clone_resets_counts_preserves_notes(self) -> None:
        original = json.loads(
            forge_create("original-agent", "Original prompt.", notes="production lessons")
        )
        cloned = json.loads(forge_clone(original["id"], name="cloned-agent"))
        assert cloned["usage_count"] == 0
        assert cloned["failure_count"] == 0
        assert cloned["notes"] == "production lessons"

    def test_forge_clone_notes_override(self) -> None:
        original = json.loads(forge_create("base", "Prompt.", notes="old note"))
        cloned = json.loads(forge_clone(original["id"], name="derived"))
        # notes is not passed as override so original notes are preserved
        assert cloned["notes"] == "old note"


class TestForgeImportSubagents:
    def _make_agents_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".claude" / "agents"
        d.mkdir(parents=True)
        return d

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert result == {"imported": [], "skipped": [], "errors": []}

    def test_imports_single_agent(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "code-reviewer.md").write_text(
            "---\nname: code-reviewer\ndescription: Reviews code\ntools:\n  - Read\n  - Bash\n---\n\nYou review code.\n"
        )
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert result["imported"] == ["code-reviewer"]
        assert result["skipped"] == []
        assert result["errors"] == []

    def test_imported_agent_registered_in_registry(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "doc-writer.md").write_text(
            "---\nname: doc-writer\ndescription: Writes docs\n---\n\nYou write documentation.\n"
        )
        forge_import_subagents(str(tmp_path))
        assert state.registry_api is not None
        agents = state.registry_api.list_agents(name_filter="doc-writer")
        assert any(a.name == "doc-writer" for a in agents)

    def test_imported_agent_has_correct_fields(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "analyst.md").write_text(
            "---\nname: analyst\ndescription: Analyzes data\ntools:\n  - Read\n  - Write\n---\n\nYou analyze data carefully.\n"
        )
        forge_import_subagents(str(tmp_path))
        assert state.registry_api is not None
        agents = state.registry_api.list_agents(name_filter="analyst")
        defn = next(a for a in agents if a.name == "analyst")
        assert defn.description == "Analyzes data"
        assert list(defn.tools) == ["Read", "Write"]
        assert defn.system_prompt == "You analyze data carefully.\n"

    def test_skips_existing_agent(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "existing.md").write_text(
            "---\nname: existing\n---\n\nAlready here.\n"
        )
        # First import registers it
        forge_import_subagents(str(tmp_path))
        # Second import should skip it
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert result["imported"] == []
        assert result["skipped"] == ["existing"]
        assert result["errors"] == []

    def test_error_on_missing_name(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "no-name.md").write_text(
            "---\ndescription: No name here\n---\n\nBody.\n"
        )
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert result["imported"] == []
        assert result["skipped"] == []
        assert len(result["errors"]) == 1
        assert "no-name.md" in result["errors"][0]
        assert "name" in result["errors"][0]

    def test_error_on_malformed_frontmatter(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "bad.md").write_text("No frontmatter at all.\n")
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert len(result["errors"]) == 1
        assert "bad.md" in result["errors"][0]

    def test_continues_after_error(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "bad.md").write_text("No frontmatter.\n")
        (agents_dir / "good.md").write_text(
            "---\nname: good-agent\n---\n\nGood prompt.\n"
        )
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert result["imported"] == ["good-agent"]
        assert len(result["errors"]) == 1

    def test_imports_multiple_agents(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        for i in range(3):
            (agents_dir / f"agent-{i}.md").write_text(
                f"---\nname: agent-{i}\n---\n\nPrompt {i}.\n"
            )
        result = json.loads(forge_import_subagents(str(tmp_path)))
        assert sorted(result["imported"]) == ["agent-0", "agent-1", "agent-2"]
        assert result["skipped"] == []
        assert result["errors"] == []

    def test_inline_tools_list(self, tmp_path: Path) -> None:
        agents_dir = self._make_agents_dir(tmp_path)
        (agents_dir / "inline.md").write_text(
            "---\nname: inline-agent\ntools: [Read, Write]\n---\n\nPrompt.\n"
        )
        forge_import_subagents(str(tmp_path))
        assert state.registry_api is not None
        agents = state.registry_api.list_agents(name_filter="inline-agent")
        defn = next(a for a in agents if a.name == "inline-agent")
        assert list(defn.tools) == ["Read", "Write"]

    def test_default_empty_dir_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When project_dir is empty, falls back to cwd."""
        monkeypatch.chdir(tmp_path)
        # No .claude/agents dir → empty result
        result = json.loads(forge_import_subagents(""))
        assert result == {"imported": [], "skipped": [], "errors": []}

    def test_roundtrip_export_then_import(self, tmp_path: Path) -> None:
        """Export an agent to .md, import it back, verify equivalent definition."""
        # Create an agent with all fields populated
        forge_create(
            "roundtrip-agent",
            "You perform roundtrip operations.",
            tools='["Read", "Write"]',
            description="A roundtrip test agent",
            tags='["test", "roundtrip"]',
        )
        export_dir = tmp_path / "export"
        result = json.loads(forge_export_subagent(name="roundtrip-agent", output_dir=str(export_dir)))
        assert result["ok"] is True

        # Import into a fresh project dir that contains the exported file
        # The agents dir from export is already at export_dir, so we need
        # a project_dir whose .claude/agents points there.
        project_dir = tmp_path / "project"
        agents_subdir = project_dir / ".claude" / "agents"
        agents_subdir.mkdir(parents=True)
        exported_file = export_dir / "roundtrip-agent.md"
        import shutil
        shutil.copy(exported_file, agents_subdir / "roundtrip-agent.md")

        # Remove the original so it's not seen as a conflict
        assert state.registry_api is not None
        originals = state.registry_api.list_agents(name_filter="roundtrip-agent")
        for orig in originals:
            state.registry_api.remove(orig.id)

        import_result = json.loads(forge_import_subagents(str(project_dir)))
        assert import_result["imported"] == ["roundtrip-agent"]

        agents = state.registry_api.list_agents(name_filter="roundtrip-agent")
        defn = next(a for a in agents if a.name == "roundtrip-agent")
        assert defn.system_prompt.strip() == "You perform roundtrip operations."
        assert list(defn.tools) == ["Read", "Write"]
        assert defn.description == "A roundtrip test agent"


class TestForgeExportSubagent:
    """Tests for forge_export_subagent MCP tool."""

    def _create_agent(
        self,
        name: str = "code-reviewer",
        system_prompt: str = "You review code carefully.",
        tools: str = '["Read", "Bash"]',
        description: str = "Reviews Python code",
        tags: str = '["python", "review"]',
    ) -> dict:  # type: ignore[type-arg]
        return json.loads(forge_create(name, system_prompt, tools=tools, description=description, tags=tags))

    def test_export_creates_md_file(self, tmp_path: Path) -> None:
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(tmp_path)))
        assert result["ok"] is True
        out_path = Path(result["path"])
        assert out_path.exists()
        assert out_path.name == "code-reviewer.md"

    def test_export_yaml_frontmatter_has_name_description_tools(self, tmp_path: Path) -> None:
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        metadata, _ = parse_frontmatter(content)
        assert metadata["name"] == "code-reviewer"
        assert metadata["description"] == "Reviews Python code"
        assert metadata["tools"] == ["Read", "Bash"]

    def test_export_body_contains_system_prompt(self, tmp_path: Path) -> None:
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        _, body = parse_frontmatter(content)
        assert "You review code carefully." in body

    def test_export_empty_description_omitted(self, tmp_path: Path) -> None:
        forge_create("no-desc-agent", "Some prompt.", description="")
        result = json.loads(forge_export_subagent(name="no-desc-agent", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        # description line should not appear in frontmatter
        assert "description:" not in content
        metadata, _ = parse_frontmatter(content)
        assert "description" not in metadata

    def test_export_empty_tools_omitted(self, tmp_path: Path) -> None:
        forge_create("no-tools-agent", "Some prompt.", tools="[]", description="Has no tools")
        result = json.loads(forge_export_subagent(name="no-tools-agent", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        # tools block should not appear
        assert "tools:" not in content
        metadata, _ = parse_frontmatter(content)
        assert "tools" not in metadata

    def test_export_with_custom_output_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "my" / "output"
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(custom_dir)))
        assert result["ok"] is True
        out_path = Path(result["path"])
        assert out_path.parent == custom_dir.resolve()
        assert out_path.exists()

    def test_export_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        deep_dir = tmp_path / "a" / "b" / "c"
        assert not deep_dir.exists()
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(deep_dir)))
        assert result["ok"] is True
        assert deep_dir.exists()

    def test_export_returns_absolute_path(self, tmp_path: Path) -> None:
        self._create_agent()
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(tmp_path)))
        out_path = Path(result["path"])
        assert out_path.is_absolute()

    def test_export_by_agent_id(self, tmp_path: Path) -> None:
        created = self._create_agent()
        result = json.loads(forge_export_subagent(agent_id=created["id"], output_dir=str(tmp_path)))
        assert result["ok"] is True
        assert Path(result["path"]).exists()

    def test_export_invalid_agent_name_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(forge_export_subagent(name="nonexistent-xyz", output_dir=str(tmp_path)))
        assert "error" in result
        assert "ok" not in result

    def test_export_no_params_returns_error(self, tmp_path: Path) -> None:
        result = json.loads(forge_export_subagent(output_dir=str(tmp_path)))
        assert "error" in result

    def test_export_does_not_include_tags_or_permissions(self, tmp_path: Path) -> None:
        """tags and permissions are Swarm-specific — must not appear in Claude Code .md."""
        self._create_agent(tags='["python", "review"]')
        result = json.loads(forge_export_subagent(name="code-reviewer", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        assert "tags:" not in content
        assert "permissions:" not in content

    def test_export_roundtrip_parse_recovers_fields(self, tmp_path: Path) -> None:
        """Export then parse should recover name, description, tools, and body."""
        self._create_agent(
            name="roundtrip-export",
            system_prompt="Perform careful analysis.",
            tools='["Read", "Write", "Bash"]',
            description="An analysis agent",
        )
        result = json.loads(forge_export_subagent(name="roundtrip-export", output_dir=str(tmp_path)))
        content = Path(result["path"]).read_text()
        metadata, body = parse_frontmatter(content)
        assert metadata["name"] == "roundtrip-export"
        assert metadata["description"] == "An analysis agent"
        assert metadata["tools"] == ["Read", "Write", "Bash"]
        assert "Perform careful analysis." in body
