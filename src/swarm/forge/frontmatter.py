"""Minimal YAML frontmatter parser and renderer for Claude Code agent files.

Handles the exact subset of YAML used by Claude Code subagent definitions:
scalars and lists only. No external dependencies (no pyyaml).
"""

from __future__ import annotations

from swarm.registry.models import AgentDefinition


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Parse YAML frontmatter and body from a markdown document.

    Handles three value forms:
    - Scalar: ``key: value``
    - Block list: ``key:`` followed by ``  - item`` lines
    - Inline list: ``key: [item1, item2]``

    Args:
        text: Full content of the markdown file.

    Returns:
        A tuple of ``(metadata_dict, body_text)``.  ``metadata_dict`` maps
        frontmatter keys to either a string scalar or a list of strings.
        ``body_text`` is everything after the closing ``---``, with leading
        blank lines stripped.

    Raises:
        ValueError: If no valid frontmatter delimiters are found.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---\n"):
        raise ValueError("No frontmatter found: document must start with '---'")

    # Content after the opening '---\n' (4 chars)
    rest = stripped[4:]

    # Find the closing delimiter: '\n---\n' or '\n---' at end of string
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        if rest.endswith("\n---"):
            end_idx = len(rest) - 4
            body_start = len(rest)
        else:
            raise ValueError("No closing '---' delimiter found in frontmatter")
    else:
        body_start = end_idx + 5  # skip '\n---\n'

    fm_block = rest[:end_idx]
    body_raw = rest[body_start:]
    # Strip leading blank lines from body
    body = body_raw.lstrip("\n")

    metadata: dict[str, str | list[str]] = {}
    lines = fm_block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines
        if not line.strip():
            i += 1
            continue

        # Block-list key: "key:" with nothing after the colon
        if ": " not in line and line.rstrip().endswith(":"):
            key = line.rstrip()[:-1]  # strip trailing ':'
            items: list[str] = []
            i += 1
            while i < len(lines) and lines[i].startswith("  - "):
                items.append(lines[i][4:].strip())
                i += 1
            metadata[key] = items
            continue

        # Scalar or inline-list: "key: value"
        if ": " in line:
            key, _, value = line.partition(": ")
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                # Inline list: [item1, item2]
                inner = value[1:-1]
                if inner.strip():
                    metadata[key] = [v.strip() for v in inner.split(",")]
                else:
                    metadata[key] = []
            else:
                metadata[key] = value
            i += 1
            continue

        # Unrecognised line — skip silently
        i += 1

    return metadata, body


def render_frontmatter(defn: AgentDefinition) -> str:
    """Render an AgentDefinition as a Claude Code-compatible ``.md`` file.

    Produces YAML frontmatter followed by the system prompt body::

        ---
        name: code-reviewer
        description: Reviews Python code
        tools:
          - Read
          - Bash
        ---

        <system_prompt>

    Empty field rules:
    - ``description``: line omitted when empty string.
    - ``tools``: entire block omitted when empty tuple.
    - ``permissions`` and ``tags``: never included (Swarm-specific).

    Args:
        defn: The agent definition to render.

    Returns:
        Full file content as a string, terminated with a newline.
    """
    lines: list[str] = ["---"]
    lines.append(f"name: {defn.name}")
    if defn.description:
        lines.append(f"description: {defn.description}")
    if defn.tools:
        lines.append("tools:")
        for tool in defn.tools:
            lines.append(f"  - {tool}")
    lines.append("---")
    lines.append("")
    lines.append(defn.system_prompt)
    return "\n".join(lines) + "\n"
