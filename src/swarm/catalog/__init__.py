"""Base agent catalog — 66 curated agents across technical, general, and business domains.

Base agents are read-only templates designed to be cloned and specialized.
They ship with Swarm and are seeded into the registry on first launch.
"""

from __future__ import annotations

from swarm.catalog.business import BUSINESS_AGENTS
from swarm.catalog.general import GENERAL_AGENTS
from swarm.catalog.technical import TECHNICAL_AGENTS

ALL_BASE_AGENTS: list[dict[str, object]] = [
    *TECHNICAL_AGENTS,
    *GENERAL_AGENTS,
    *BUSINESS_AGENTS,
]

__all__ = [
    "ALL_BASE_AGENTS",
    "TECHNICAL_AGENTS",
    "GENERAL_AGENTS",
    "BUSINESS_AGENTS",
]
