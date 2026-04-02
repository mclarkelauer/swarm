"""MCP server entry point.

Reads ``SWARM_BASE_DIR`` and ``SWARM_PLANS_DIR`` from the environment,
initializes the ForgeAPI and RegistryAPI, then starts the FastMCP server.
"""

from __future__ import annotations

import os
from pathlib import Path

# Import tool modules for side-effect registration
import swarm.mcp.artifact_tools as _artifact_tools  # noqa: F401
import swarm.mcp.discovery_tools as _discovery_tools  # noqa: F401
import swarm.mcp.executor_tools as _executor_tools  # noqa: F401
import swarm.mcp.forge_tools as _forge_tools  # noqa: F401
import swarm.mcp.memory_tools as _memory_tools  # noqa: F401
import swarm.mcp.message_tools as _message_tools  # noqa: F401
import swarm.mcp.plan_tools as _plan_tools  # noqa: F401
import swarm.mcp.registry_tools as _registry_tools  # noqa: F401
from swarm.dirs import ensure_base_dir
from swarm.forge.api import ForgeAPI
from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.memory.api import MemoryAPI
from swarm.messaging.api import MessageAPI
from swarm.registry.api import RegistryAPI
from swarm.registry.sources import SourcePlugin
from swarm.registry.sources.project import ProjectDirectorySource


def main() -> None:
    """Entry point for the ``swarm-mcp`` console script."""
    base_dir = Path(os.environ.get("SWARM_BASE_DIR", str(Path.home() / ".swarm")))
    plans_dir = os.environ.get("SWARM_PLANS_DIR", os.getcwd())

    ensure_base_dir(base_dir)

    # Auto-discover project-local agent definitions
    sources: list[SourcePlugin] = []
    project_agents = Path(plans_dir) / ".swarm" / "agents"
    if project_agents.is_dir():
        sources.append(ProjectDirectorySource(Path(plans_dir)))

    # Initialize shared state
    state.registry_api = RegistryAPI(base_dir / "registry.db")
    state.forge_api = ForgeAPI(base_dir / "registry.db", base_dir / "forge", sources=sources)
    state.memory_api = MemoryAPI(db_path=base_dir / "memory.db")
    state.message_api = MessageAPI(db_path=base_dir / "messages.db")
    state.plans_dir = plans_dir

    mcp.run()


if __name__ == "__main__":
    main()
