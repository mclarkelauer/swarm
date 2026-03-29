"""Tests for swarm.forge.frontmatter parse_frontmatter and render_frontmatter."""

from __future__ import annotations

import pytest

from swarm.forge.frontmatter import parse_frontmatter, render_frontmatter
from swarm.registry.models import AgentDefinition


def _make_defn(
    name: str = "test-agent",
    system_prompt: str = "You are a helpful assistant.",
    description: str = "A test agent",
    tools: tuple[str, ...] = ("Read", "Write"),
) -> AgentDefinition:
    return AgentDefinition(
        id="test-id-123",
        name=name,
        system_prompt=system_prompt,
        description=description,
        tools=tools,
    )


class TestParseFrontmatterScalars:
    def test_simple_scalar(self) -> None:
        text = "---\nname: code-reviewer\n---\n\nBody here.\n"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "code-reviewer"
        assert body == "Body here.\n"

    def test_multiple_scalars(self) -> None:
        text = "---\nname: agent\ndescription: Does things\n---\n\nPrompt.\n"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "agent"
        assert meta["description"] == "Does things"
        assert body == "Prompt.\n"

    def test_colon_in_value_preserved(self) -> None:
        text = "---\ndescription: Handles http://example.com requests\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["description"] == "Handles http://example.com requests"

    def test_leading_whitespace_stripped(self) -> None:
        text = "\n\n---\nname: agent\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "agent"


class TestParseFrontmatterLists:
    def test_block_list(self) -> None:
        text = "---\nname: agent\ntools:\n  - Read\n  - Bash\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["tools"] == ["Read", "Bash"]

    def test_inline_list(self) -> None:
        text = "---\nname: agent\ntools: [Read, Bash, Write]\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["tools"] == ["Read", "Bash", "Write"]

    def test_empty_inline_list(self) -> None:
        text = "---\nname: agent\ntools: []\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["tools"] == []

    def test_empty_block_list(self) -> None:
        text = "---\nname: agent\ntools:\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["tools"] == []

    def test_inline_list_whitespace_stripped(self) -> None:
        text = "---\nname: agent\ntools: [ Read , Bash , Write ]\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["tools"] == ["Read", "Bash", "Write"]


class TestParseFrontmatterBody:
    def test_body_leading_blank_lines_stripped(self) -> None:
        text = "---\nname: agent\n---\n\n\nActual body.\n"
        _, body = parse_frontmatter(text)
        assert body == "Actual body.\n"

    def test_body_multiline(self) -> None:
        text = "---\nname: agent\n---\n\nLine 1.\nLine 2.\n"
        _, body = parse_frontmatter(text)
        assert body == "Line 1.\nLine 2.\n"

    def test_empty_body(self) -> None:
        text = "---\nname: agent\n---\n"
        _, body = parse_frontmatter(text)
        assert body == ""

    def test_body_retains_internal_blank_lines(self) -> None:
        text = "---\nname: agent\n---\n\nPart one.\n\nPart two.\n"
        _, body = parse_frontmatter(text)
        assert "Part one." in body
        assert "Part two." in body
        assert body.index("Part one.") < body.index("Part two.")


class TestParseFrontmatterErrors:
    def test_no_opening_delimiter(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            parse_frontmatter("Just text, no frontmatter.\n")

    def test_no_closing_delimiter(self) -> None:
        with pytest.raises(ValueError, match="closing"):
            parse_frontmatter("---\nname: agent\n")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_frontmatter("")


class TestParseFrontmatterUnknownKeys:
    def test_unknown_keys_silently_ignored(self) -> None:
        text = "---\nname: agent\ncustom_field: some value\n---\n\nBody.\n"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "agent"
        assert meta["custom_field"] == "some value"


class TestRenderFrontmatter:
    """Tests for render_frontmatter."""

    def test_render_all_fields_populated(self) -> None:
        defn = _make_defn()
        result = render_frontmatter(defn)
        assert result.startswith("---\n")
        assert "name: test-agent" in result
        assert "description: A test agent" in result
        assert "tools:" in result
        assert "  - Read" in result
        assert "  - Write" in result
        assert "You are a helpful assistant." in result

    def test_render_output_terminates_with_newline(self) -> None:
        defn = _make_defn()
        result = render_frontmatter(defn)
        assert result.endswith("\n")

    def test_render_has_two_frontmatter_delimiters(self) -> None:
        defn = _make_defn()
        result = render_frontmatter(defn)
        # Should have exactly the opening --- and closing ---
        lines = result.splitlines()
        delimiter_positions = [i for i, line in enumerate(lines) if line == "---"]
        assert len(delimiter_positions) == 2
        assert delimiter_positions[0] == 0  # first line

    def test_render_empty_description_omitted(self) -> None:
        defn = _make_defn(description="")
        result = render_frontmatter(defn)
        assert "description:" not in result

    def test_render_empty_tools_block_omitted(self) -> None:
        defn = _make_defn(tools=())
        result = render_frontmatter(defn)
        assert "tools:" not in result
        assert "  - " not in result

    def test_render_single_tool(self) -> None:
        defn = _make_defn(tools=("Read",))
        result = render_frontmatter(defn)
        assert "tools:\n  - Read\n" in result

    def test_render_tags_not_included(self) -> None:
        """Tags are Swarm-specific and must not appear in rendered output."""
        defn = AgentDefinition(
            id="x",
            name="tagged-agent",
            system_prompt="prompt",
            tags=("python", "review"),
        )
        result = render_frontmatter(defn)
        assert "tags:" not in result

    def test_render_permissions_not_included(self) -> None:
        """Permissions are Swarm-specific and must not appear in rendered output."""
        defn = AgentDefinition(
            id="x",
            name="perm-agent",
            system_prompt="prompt",
            permissions=("read", "write"),
        )
        result = render_frontmatter(defn)
        assert "permissions:" not in result

    def test_render_system_prompt_in_body(self) -> None:
        defn = _make_defn(system_prompt="Do things carefully.\nStep by step.")
        result = render_frontmatter(defn)
        assert "Do things carefully.\nStep by step." in result

    def test_render_blank_line_between_delimiter_and_body(self) -> None:
        """The closing --- must be followed by a blank line before the body."""
        defn = _make_defn()
        result = render_frontmatter(defn)
        # closing --- followed immediately by newline then empty line then body
        assert "\n---\n\n" in result


class TestRenderParseRoundtrip:
    """Roundtrip: render_frontmatter -> parse_frontmatter recovers original values."""

    def test_roundtrip_recovers_name(self) -> None:
        defn = _make_defn(name="my-special-agent")
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert meta["name"] == "my-special-agent"

    def test_roundtrip_recovers_description(self) -> None:
        defn = _make_defn(description="Does important things.")
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert meta["description"] == "Does important things."

    def test_roundtrip_recovers_tools(self) -> None:
        defn = _make_defn(tools=("Read", "Write", "Bash"))
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert meta["tools"] == ["Read", "Write", "Bash"]

    def test_roundtrip_recovers_system_prompt_body(self) -> None:
        defn = _make_defn(system_prompt="You analyze data.\nBe precise.")
        result = render_frontmatter(defn)
        _, body = parse_frontmatter(result)
        assert "You analyze data." in body
        assert "Be precise." in body

    def test_roundtrip_empty_description_remains_absent(self) -> None:
        defn = _make_defn(description="")
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert "description" not in meta

    def test_roundtrip_empty_tools_remain_absent(self) -> None:
        defn = _make_defn(tools=())
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert "tools" not in meta

    def test_roundtrip_colon_in_description_preserved(self) -> None:
        defn = _make_defn(description="Handles http://example.com queries")
        result = render_frontmatter(defn)
        meta, _ = parse_frontmatter(result)
        assert meta["description"] == "Handles http://example.com queries"
