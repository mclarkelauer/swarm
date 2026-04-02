"""Memory injection helpers for agent system prompts."""

from __future__ import annotations

from swarm.memory.models import MemoryEntry


def format_memories_for_prompt(
    memories: list[MemoryEntry],
    *,
    max_chars: int = 4000,
) -> str:
    """Format a list of memories as a system prompt section.

    Produces a structured text block that can be appended to an agent's
    system prompt. Respects a character budget to avoid prompt bloat.

    Args:
        memories: List of MemoryEntry objects (pre-filtered/sorted).
        max_chars: Maximum total characters for the memory block.

    Returns:
        Formatted string, or empty string if no memories.
    """
    if not memories:
        return ""

    type_labels = {
        "episodic": "Past Experience",
        "semantic": "Known Fact",
        "procedural": "Procedure",
    }

    lines: list[str] = ["<agent-memory>"]
    char_count = len(lines[0])

    for mem in memories:
        label = type_labels.get(mem.memory_type, mem.memory_type)
        entry = f"[{label}] {mem.content}"
        if char_count + len(entry) + 1 > max_chars:
            break
        lines.append(entry)
        char_count += len(entry) + 1

    lines.append("</agent-memory>")
    return "\n".join(lines)
