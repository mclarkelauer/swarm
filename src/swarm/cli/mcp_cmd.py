"""CLI command: swarm mcp-config."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click


@click.command("mcp-config")
@click.option("--plans-dir", default=".", help="Plans directory to configure.")
@click.option("--base-dir", default=None, help="Swarm base directory (default: ~/.swarm).")
@click.option("--json-file", "as_json", is_flag=True, help="Output as a full MCP config file.")
def mcp_config(plans_dir: str, base_dir: str | None, as_json: bool) -> None:
    """Print the MCP server configuration for Claude Code.

    Add the output to ~/.claude/settings.json under mcpServers,
    or save to a file and pass via ``claude --mcp-config <file>``.

    \b
    Examples:
        swarm mcp-config                          # print server block
        swarm mcp-config --json-file > mcp.json   # full config file
        claude --mcp-config <(swarm mcp-config --json-file)
    """
    # Resolve swarm-mcp command path
    mcp_cmd = "swarm-mcp"
    venv_bin = Path(sys.executable).parent / "swarm-mcp"
    if venv_bin.exists():
        mcp_cmd = str(venv_bin)
    elif shutil.which("swarm-mcp"):
        found = shutil.which("swarm-mcp")
        if found:
            mcp_cmd = found

    resolved_base = base_dir or str(Path.home() / ".swarm")
    resolved_plans = str(Path(plans_dir).resolve())

    server_block = {
        "command": mcp_cmd,
        "env": {
            "SWARM_BASE_DIR": resolved_base,
            "SWARM_PLANS_DIR": resolved_plans,
        },
    }

    if as_json:
        click.echo(json.dumps({"mcpServers": {"swarm": server_block}}, indent=2))
    else:
        click.echo(json.dumps({"swarm": server_block}, indent=2))
