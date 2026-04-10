"""Shared global state for the MCP server.

Populated by ``server.main()`` before the FastMCP server starts.
All tool modules read from these module-level variables.
"""

from __future__ import annotations

from swarm.context.api import SharedContextAPI
from swarm.forge.api import ForgeAPI
from swarm.memory.api import MemoryAPI
from swarm.messaging.api import MessageAPI
from swarm.registry.api import RegistryAPI

registry_api: RegistryAPI | None = None
forge_api: ForgeAPI | None = None
memory_api: MemoryAPI | None = None
message_api: MessageAPI | None = None
context_api: SharedContextAPI | None = None
plans_dir: str = ""
