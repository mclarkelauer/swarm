"""CLI commands for the Agent Forge.

``swarm forge design`` spawns a Claude CLI instance that designs a new agent
definition from a plain-English task description, then registers it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from swarm.cli.launch import launch_claude_session
from swarm.config import load_config
from swarm.dirs import ensure_base_dir
from swarm.forge.api import ForgeAPI
from swarm.forge.prompts import FORGE_SYSTEM_PROMPT, build_forge_prompt

_FORGE_SESSION_PROMPT = """\
You are the Swarm Agent Forge — a specialized session for designing, creating, \
and managing agent definitions.

You have Swarm MCP tools available:

FORGE TOOLS:
- forge_list: List all agent definitions (with optional name filter)
- forge_get: Get a single agent by ID or name
- forge_create: Create a new agent definition (name, system_prompt, tools, permissions)
- forge_clone: Clone an existing agent with overrides
- forge_suggest: Search for agents matching a task description
- forge_remove: Remove an agent definition

REGISTRY TOOLS:
- registry_list, registry_inspect, registry_search, registry_remove

Your workflow:
1. Understand what kind of agent the user needs
2. Search existing agents with forge_suggest to avoid duplicates
3. Design the agent definition — name, detailed system prompt, tools, permissions
4. Create it with forge_create
5. Show the user what was created

Be conversational and help the user iterate on agent designs.
"""


def _get_forge() -> ForgeAPI:
    config = load_config()
    ensure_base_dir(config.base_dir)
    return ForgeAPI(config.base_dir / "registry.db", config.base_dir / "forge")


@click.group(invoke_without_command=True)
@click.pass_context
def forge(ctx: click.Context) -> None:
    """Design, suggest, and manage agents via the forge.

    Run without arguments to start an interactive forge session.
    """
    if ctx.invoked_subcommand is None:
        launch_claude_session(
            system_prompt=_FORGE_SESSION_PROMPT,
            session_name="swarm-forge",
        )


@forge.command()
@click.argument("task")
@click.option("--name", default=None, help="Override the generated agent name.")
@click.option("--dry-run", is_flag=True, help="Show what Claude would create without registering.")
def design(task: str, name: str | None, dry_run: bool) -> None:
    """Design a new agent using Claude.

    Describe the task in plain English and Claude will produce an agent
    definition — name, system prompt, tools, and permissions — then
    register it in the forge.

    Examples:

        swarm forge design "review Python code for security vulnerabilities"

        swarm forge design "write integration tests for REST APIs" --name api-tester

        swarm forge design "summarize Slack threads" --dry-run
    """
    console = Console()
    api = _get_forge()

    # Gather existing agents for context
    existing = api.suggest_agent("")

    # Build the prompt
    task_prompt = build_forge_prompt(task, existing)

    config = load_config()
    timeout = config.forge_timeout

    console.print(f"[bold]Forging agent for:[/bold] {task}")
    console.print("[dim]Calling Claude...[/dim]")

    # Invoke Claude
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[red]Error: claude CLI not found.[/red]")
        console.print("Install with: npm install -g @anthropic-ai/claude-code")
        raise SystemExit(1)

    cmd = [
        claude_cmd,
        "--dangerously-skip-permissions",
        "--system-prompt", FORGE_SYSTEM_PROMPT,
        "--output-format", "json",
        "--print",
        "-p", task_prompt,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        console.print(f"[red]Claude timed out after {timeout}s.[/red]")
        raise SystemExit(1) from exc
    except FileNotFoundError as exc:
        console.print("[red]Error: claude CLI not found.[/red]")
        raise SystemExit(1) from exc

    if result.returncode != 0 and not result.stdout.strip():
        console.print(f"[red]Claude failed (exit {result.returncode}):[/red]")
        console.print(result.stderr[:500] if result.stderr else "unknown error")
        raise SystemExit(1)

    # Parse the JSON response
    raw = result.stdout.strip()
    definition = _parse_definition(raw)
    if definition is None:
        console.print("[red]Could not parse agent definition from Claude's response.[/red]")
        console.print("[dim]Raw output:[/dim]")
        console.print(raw[:1000])
        raise SystemExit(1)

    # Apply name override
    if name:
        definition["name"] = name

    # Display the definition
    console.print()
    console.print("[bold green]Agent definition:[/bold green]")
    console.print(f"  [bold]Name:[/bold]        {definition['name']}")
    console.print(f"  [bold]Tools:[/bold]       {definition.get('tools', [])}")
    console.print(f"  [bold]Permissions:[/bold] {definition.get('permissions', [])}")
    console.print("  [bold]Prompt:[/bold]")
    for line in definition.get("system_prompt", "").split("\n")[:10]:
        console.print(f"    {line}")
    prompt_lines = definition.get("system_prompt", "").split("\n")
    if len(prompt_lines) > 10:
        console.print(f"    [dim]... ({len(prompt_lines) - 10} more lines)[/dim]")

    if dry_run:
        console.print()
        console.print("[yellow]Dry run — not registered.[/yellow]")
        console.print("[dim]JSON:[/dim]")
        console.print(json.dumps(definition, indent=2))
        return

    # Register
    defn = api.create_agent(
        name=definition["name"],
        system_prompt=definition.get("system_prompt", ""),
        tools=definition.get("tools", []),
        permissions=definition.get("permissions", []),
    )
    console.print()
    console.print(f"[bold green]Registered:[/bold green] {defn.name} ({defn.id})")


@forge.command()
@click.argument("query")
def suggest(query: str) -> None:
    """Find existing agents that match a task description.

    Searches the registry and all source plugins by name and prompt.

    Examples:

        swarm forge suggest "code review"

        swarm forge suggest "testing"
    """
    console = Console()
    api = _get_forge()
    results = api.suggest_agent(query)

    if not results:
        console.print(f"[dim]No agents matching '{query}'.[/dim]")
        console.print("[dim]Use 'swarm forge design' to create one.[/dim]")
        return

    table = Table(title=f"Agents matching '{query}'")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Prompt", max_width=60)
    for a in results:
        table.add_row(a.name, a.id[:12], a.system_prompt[:60])
    console.print(table)


def _parse_definition(raw: str) -> dict[str, Any] | None:
    """Parse an agent definition from Claude's output.

    Handles both clean JSON output and JSON embedded in text.
    """
    # Try direct parse first
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "name" in data:
            return _normalize(data)
        # Output-format json wraps in {"type":"result","result":"..."}
        if isinstance(data, dict) and "result" in data:
            inner = data["result"]
            if isinstance(inner, str):
                return _parse_definition(inner)
            if isinstance(inner, dict) and "name" in inner:
                return _normalize(inner)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from text (Claude sometimes wraps in markdown)
    for start_marker in ["{", "```json\n{", "```\n{"]:
        idx = raw.find(start_marker)
        if idx >= 0:
            json_start = raw.index("{", idx)
            # Find matching closing brace
            depth = 0
            for i, ch in enumerate(raw[json_start:], json_start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(raw[json_start:i + 1])
                            if isinstance(data, dict) and "name" in data:
                                return _normalize(data)
                        except json.JSONDecodeError:
                            continue
                        break

    return None


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize an agent definition dict to expected types."""
    result: dict[str, object] = {
        "name": str(data.get("name", "")),
        "system_prompt": str(data.get("system_prompt", "")),
    }
    tools = data.get("tools", [])
    result["tools"] = list(tools) if isinstance(tools, (list, tuple)) else []
    perms = data.get("permissions", [])
    result["permissions"] = list(perms) if isinstance(perms, (list, tuple)) else []
    return result
