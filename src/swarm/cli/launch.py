"""Shared logic for launching interactive Claude Code sessions with Swarm MCP tools."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import click

from swarm.catalog.seed import seed_base_agents
from swarm.config import load_config
from swarm.dirs import ensure_base_dir
from swarm.registry.api import RegistryAPI


def _resolve_mcp_cmd() -> str:
    """Find the swarm-mcp binary."""
    venv_bin = Path(sys.executable).parent / "swarm-mcp"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("swarm-mcp")
    if found:
        return found
    return "swarm-mcp"


def _resolve_claude_cmd() -> str:
    """Find the claude binary, or exit with an error."""
    found = shutil.which("claude")
    if found:
        return found
    click.echo("Error: claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code", err=True)
    raise SystemExit(1)


_BANNERS: dict[str, str] = {
    "swarm-orchestrator": """\
\033[1;36m╔══════════════════════════════════════════════════════════╗
║  SWARM ORCHESTRATOR                                     ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  You're in a Swarm orchestrator session.                ║
║  Claude has MCP tools for managing agents and plans.     ║
║                                                          ║
║  Getting started:                                        ║
║    - Describe your goal and Claude will help plan it     ║
║    - Claude can create agents with forge_create           ║
║    - Claude can build execution plans with plan_create   ║
║    - Claude can spawn subagents to execute steps         ║
║                                                          ║
║  Useful commands:                                        ║
║    "list my agents"     — show registered agent defs     ║
║    "create a plan for..." — design an execution plan     ║
║    "execute the plan"   — spawn agents for ready steps   ║
║                                                          ║
║  CLI commands still work outside this session:           ║
║    swarm forge list    — list agents                    ║
║    swarm plan show X   — display a plan                 ║
║    swarm mcp-config    — show MCP config                ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝\033[0m
""",
    "swarm-forge": """\
\033[1;35m╔══════════════════════════════════════════════════════════╗
║  SWARM FORGE                                            ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  You're in a Swarm forge session.                       ║
║  Claude has MCP tools for designing agent definitions.   ║
║                                                          ║
║  Getting started:                                        ║
║    - Describe the kind of agent you need                 ║
║    - Claude will search existing agents first            ║
║    - Then design and register a new definition           ║
║                                                          ║
║  Useful commands:                                        ║
║    "show me all agents"     — list registered defs       ║
║    "create an agent that..." — design a new agent        ║
║    "clone X with..."        — clone with overrides       ║
║                                                          ║
║  CLI commands still work outside this session:           ║
║    swarm forge list        — list agents                ║
║    swarm forge suggest X   — search agents              ║
║    swarm registry inspect X — agent details             ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝\033[0m
""",
}


def launch_claude_session(
    system_prompt: str,
    session_name: str = "",
) -> None:
    """Launch an interactive Claude Code session with Swarm MCP tools attached.

    Prints a banner, then replaces the current process with ``claude``
    via ``os.execvp``.

    Args:
        system_prompt: System prompt for the session.
        session_name: Optional display name for the session.
    """
    # Print banner before exec replaces us
    banner = _BANNERS.get(session_name, "")
    if banner:
        click.echo(banner)

    config = load_config()
    ensure_base_dir(config.base_dir)

    # Seed the base agent catalog before launching — idempotent, fast when current.
    try:
        with RegistryAPI(config.base_dir / "registry.db") as registry:
            seed_base_agents(registry)
    except Exception:
        # Never block session launch due to a seeding failure.
        pass

    claude_cmd = _resolve_claude_cmd()
    mcp_cmd = _resolve_mcp_cmd()

    plans_dir = str(Path.cwd())

    # Build MCP config inline via env vars — Claude CLI reads --mcp-config
    # We write a temp config file that points to our MCP server
    import json

    mcp_config = {
        "mcpServers": {
            "swarm": {
                "command": mcp_cmd,
                "env": {
                    "SWARM_BASE_DIR": str(config.base_dir),
                    "SWARM_PLANS_DIR": plans_dir,
                },
            }
        }
    }

    # Write to a deterministic path so reconnecting works
    config_dir = config.base_dir / "run"
    config_dir.mkdir(parents=True, exist_ok=True)
    mcp_config_path = config_dir / "mcp_config.json"
    mcp_config_path.write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")

    cmd = [
        claude_cmd,
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--mcp-config", str(mcp_config_path),
    ]

    if session_name:
        cmd.extend(["--name", session_name])

    # Replace current process
    os.execvp(claude_cmd, cmd)
