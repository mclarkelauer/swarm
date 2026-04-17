"""Tests for swarm.memory.injection: format_memories_for_prompt."""

from __future__ import annotations

from swarm.memory.injection import format_memories_for_prompt
from swarm.memory.models import MemoryEntry


def _make_entry(
    content: str,
    memory_type: str = "semantic",
    entry_id: str = "id",
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        agent_name="agent",
        content=content,
        memory_type=memory_type,
    )


class TestFormatMemoriesForPrompt:
    def test_format_empty_memories_returns_empty(self) -> None:
        result = format_memories_for_prompt([])
        assert result == ""

    def test_format_single_memory(self) -> None:
        memories = [_make_entry("Python uses indentation.")]
        result = format_memories_for_prompt(memories)
        assert "<agent-memory>" in result
        assert "</agent-memory>" in result
        assert "[Known Fact] Python uses indentation." in result

    def test_format_multiple_memory_types(self) -> None:
        memories = [
            _make_entry("Deployment failed on Friday.", memory_type="episodic"),
            _make_entry("Always run lint before commit.", memory_type="procedural"),
            _make_entry("The API returns JSON.", memory_type="semantic"),
        ]
        result = format_memories_for_prompt(memories)
        assert "[Past Experience] Deployment failed on Friday." in result
        assert "[Procedure] Always run lint before commit." in result
        assert "[Known Fact] The API returns JSON." in result

    def test_format_respects_char_budget(self) -> None:
        # Create memories that together exceed a small budget
        memories = [
            _make_entry("A" * 50, entry_id="1"),
            _make_entry("B" * 50, entry_id="2"),
            _make_entry("C" * 50, entry_id="3"),
        ]
        # Budget is small enough to fit only the header + one or two entries
        result = format_memories_for_prompt(memories, max_chars=100)
        assert "<agent-memory>" in result
        assert "</agent-memory>" in result
        # At least one entry should be included, but not all three
        lines = result.strip().split("\n")
        # Remove the wrapper tags
        content_lines = [
            line for line in lines
            if not line.startswith("<") and not line.startswith("</")
        ]
        assert len(content_lines) < 3

    def test_format_type_labels(self) -> None:
        episodic = _make_entry("Event.", memory_type="episodic")
        semantic = _make_entry("Fact.", memory_type="semantic")
        procedural = _make_entry("Step.", memory_type="procedural")

        r_e = format_memories_for_prompt([episodic])
        assert "[Past Experience]" in r_e

        r_s = format_memories_for_prompt([semantic])
        assert "[Known Fact]" in r_s

        r_p = format_memories_for_prompt([procedural])
        assert "[Procedure]" in r_p

    def test_format_unknown_type_uses_raw_name(self) -> None:
        entry = _make_entry("Custom memory.", memory_type="custom_type")
        result = format_memories_for_prompt([entry])
        assert "[custom_type] Custom memory." in result

    def test_format_output_structure(self) -> None:
        memories = [_make_entry("Fact one."), _make_entry("Fact two.", entry_id="id2")]
        result = format_memories_for_prompt(memories)
        lines = result.strip().split("\n")
        assert lines[0] == "<agent-memory>"
        assert lines[-1] == "</agent-memory>"
        assert len(lines) == 4  # header + 2 entries + footer
