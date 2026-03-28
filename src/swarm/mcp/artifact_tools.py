"""MCP tools for artifact declaration."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.mcp import state
from swarm.mcp.instance import mcp


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
