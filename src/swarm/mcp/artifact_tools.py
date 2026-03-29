"""MCP tools for artifact declaration and retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm.mcp import state
from swarm.mcp.instance import mcp


def _resolve_artifacts_file(plan_dir: str) -> Path:
    """Return the Path to artifacts.json given an optional plan_dir override."""
    if plan_dir:
        return Path(plan_dir) / "artifacts.json"
    if state.plans_dir:
        return Path(state.plans_dir) / "artifacts.json"
    return Path.cwd() / "artifacts.json"


def _read_artifacts(artifacts_file: Path) -> list[dict[str, Any]]:
    """Parse a newline-delimited JSON artifacts file, skipping corrupt lines."""
    entries: list[dict[str, Any]] = []
    for line in artifacts_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


@mcp.tool()
def artifact_declare(path: str, description: str, agent_id: str = "") -> str:
    """Declare a file as an output artifact.

    Appends the declaration to ``artifacts.json`` in the plans directory.

    Args:
        path: Path to the artifact file.
        description: Human-readable description of the artifact.
        agent_id: Optional agent that produced this artifact.
    """
    plans_dir = Path(state.plans_dir) if state.plans_dir else Path.cwd()
    artifacts_file = plans_dir / "artifacts.json"
    plans_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "agent_id": agent_id,
        "path": path,
        "description": description,
    }

    with artifacts_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return json.dumps({"ok": True, "artifact": entry})


@mcp.tool()
def artifact_list(plan_dir: str = "") -> str:
    """Return all artifact entries from artifacts.json as a JSON array.

    Args:
        plan_dir: Optional directory containing artifacts.json.  When empty,
            falls back to ``state.plans_dir`` then the current working directory.
    """
    artifacts_file = _resolve_artifacts_file(plan_dir)
    if not artifacts_file.exists():
        return "[]"
    entries = _read_artifacts(artifacts_file)
    return json.dumps(entries)


@mcp.tool()
def artifact_get(path: str, plan_dir: str = "", max_lines: str = "50") -> str:
    """Return content and metadata for a single artifact file.

    Args:
        path: Path to the artifact file (absolute or relative to plan_dir).
        plan_dir: Optional directory containing artifacts.json and artifact files.
        max_lines: Maximum number of lines to return (parsed from string per MCP
            convention).  Defaults to ``"50"``.
    """
    try:
        limit = int(max_lines)
    except ValueError:
        return json.dumps({"error": f"Invalid max_lines: {max_lines!r}"})
    if limit < 1:
        limit = 50

    artifacts_file = _resolve_artifacts_file(plan_dir)

    # Look up metadata in artifacts.json (None when file absent or path unregistered).
    metadata: dict[str, Any] | None = None
    if artifacts_file.exists():
        for entry in _read_artifacts(artifacts_file):
            if entry.get("path") == path:
                metadata = entry
                break

    # Resolve the actual file: try as-is first, then relative to plan_dir.
    candidate = Path(path)
    if not candidate.exists() and plan_dir:
        candidate = Path(plan_dir) / path

    if not candidate.exists():
        return json.dumps(
            {
                "metadata": metadata,
                "content": None,
                "truncated": False,
                "error": f"File not found: {path}",
            }
        )

    lines = candidate.read_text(encoding="utf-8").splitlines()
    truncated = len(lines) > limit
    content = "\n".join(lines[:limit])

    return json.dumps(
        {
            "metadata": metadata,
            "content": content,
            "truncated": truncated,
        }
    )
