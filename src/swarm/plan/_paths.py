"""Shared filesystem helpers for plan management.

Single source of truth for resolving a plan-directory path from a
caller-supplied string, the configured MCP state, or an upward filesystem
walk for an existing plan project.
"""

from __future__ import annotations

from pathlib import Path

from swarm.plan.discovery import find_plans_dir


def resolve_plans_dir(plans_dir: str) -> Path:
    """Resolve the plans directory using the safer MCP-style semantics.

    Resolution order:

    1. Non-empty *plans_dir* values that are not the literal ``"."``
       sentinel are returned verbatim as a :class:`Path`.
    2. The configured MCP state default (``swarm.mcp.state.plans_dir``)
       is consulted next, when set.
    3. :func:`swarm.plan.discovery.find_plans_dir` walks up from
       :func:`Path.cwd` looking for an existing plan project.
    4. ``Path.cwd()`` is the final fallback.

    The empty string ``""`` and the click-default ``"."`` are both
    treated as "use the configured/discovered default" — this matches
    the MCP behaviour and was chosen as the safer of the two prior
    semantics because it avoids surprising the caller with a literal
    ``./`` write target when they meant "use whatever Swarm normally
    uses".
    """
    # Local import keeps this module free of an MCP import cycle when
    # the plan package is loaded standalone (e.g. by templates).
    from swarm.mcp import state

    if plans_dir and plans_dir != ".":
        return Path(plans_dir)
    if state.plans_dir:
        return Path(state.plans_dir)
    return find_plans_dir() or Path.cwd()
