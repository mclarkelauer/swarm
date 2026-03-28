"""Shared global state for the MCP server.

Populated by ``server.main()`` before the FastMCP server starts.
All tool modules read from these module-level variables.
"""

from __future__ import annotations

from swarm.forge.api import ForgeAPI
from swarm.registry.api import RegistryAPI

registry_api: RegistryAPI | None = None
forge_api: ForgeAPI | None = None
plans_dir: str = ""
