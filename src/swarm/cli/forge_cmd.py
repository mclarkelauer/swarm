"""CLI commands for the Agent Forge.

``swarm forge design`` spawns a Claude CLI instance that designs a new agent
definition from a plain-English task description, then registers it.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click
from rich.console import Console
from rich.status import Status
from rich.table import Table

from swarm.cli._helpers import get_forge, get_registry
from swarm.cli.launch import launch_claude_session
from swarm.config import load_config
from swarm.forge.prompts import FORGE_SYSTEM_PROMPT, build_forge_prompt

_FORGE_SESSION_PROMPT = """\
You are the Swarm Agent Forge — a specialized session for designing, creating, \
and managing agent definitions.

DISCOVER & BROWSE:
- swarm_discover(query) — lightweight catalog (name+description+tags). Start here.
- forge_suggest_ranked(query) — semantic search with LLM re-ranking prompt
- forge_get(id_or_name) — full agent details including system prompt

CREATE & MODIFY:
- forge_create — create a new agent; always set description (one sentence) and \
tags (kebab-case) for discoverability; use notes for lessons learned
- forge_clone — clone with overrides; preserves provenance and notes
- forge_remove — remove an agent definition

IMPORT / EXPORT:
- forge_export_subagent — export to .claude/agents/<name>.md for native Claude \
Code integration
- forge_import_subagents — import .claude/agents/*.md files into the registry

PERFORMANCE FEEDBACK:
- forge_annotate_from_run — update usage_count, failure_count, and notes from \
a completed run log

REGISTRY (low-level):
- registry_list, registry_inspect, registry_search, registry_remove

WORKFLOW:
1. Use swarm_discover or forge_suggest_ranked to check for existing agents first
2. Design the agent — name, detailed system prompt, tools, permissions
3. Set description (one sentence), tags, and notes when creating
4. Create with forge_create; clone existing agents when the overlap is high
5. Export to .claude/agents/ when the agent should run natively in Claude Code
6. After runs, call forge_annotate_from_run to record performance data

Be conversational and help the user iterate on agent designs.
"""


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
    api = get_forge()

    # Gather existing agents for context
    existing = api.suggest_agent("")

    # Build the prompt
    task_prompt = build_forge_prompt(task, existing)

    config = load_config()
    timeout = config.forge_timeout

    console.print(f"[bold]Forging agent for:[/bold] {task}")

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
        result = _run_with_spinner(cmd, timeout, console)
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
    api = get_forge()
    results = api.suggest_agent(query)

    if not results:
        console.print(f"[dim]No agents matching '{query}'.[/dim]")
        console.print("[dim]Use 'swarm forge design' to create one.[/dim]")
        return

    table = Table(title=f"Agents matching '{query}'")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Prompt", max_width=60)
    table.add_column("Parent", style="dim", max_width=12)
    for a in results:
        table.add_row(a.name, a.id[:12], a.system_prompt[:60], (a.parent_id or "")[:12])
    console.print(table)


def _run_with_spinner(
    cmd: list[str], timeout: int, console: Console
) -> SimpleNamespace:
    """Run a subprocess with a Rich spinner showing elapsed time."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.monotonic()
    with Status("[bold blue]Calling Claude...[/bold blue]", console=console, spinner="dots"):
        while proc.poll() is None:
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                proc.kill()
                proc.wait()
                console.print(f"[red]Claude timed out after {timeout}s.[/red]")
                raise SystemExit(1)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1.0)
    stdout = proc.stdout.read() if proc.stdout else ""
    stderr = proc.stderr.read() if proc.stderr else ""
    return SimpleNamespace(returncode=proc.returncode, stdout=stdout, stderr=stderr)


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


@forge.command()
@click.argument("identifier")
def edit(identifier: str) -> None:
    """Edit an agent's system prompt in $EDITOR.

    Resolves the agent by name or ID, opens the system prompt in your
    editor, and on save creates a clone with the updated prompt.

    Examples:

        swarm forge edit code-reviewer

        swarm forge edit 3f8a2b1c-...
    """
    console = Console()
    registry = get_registry()
    api = get_forge()
    try:
        defn = registry.resolve_agent(identifier)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e

    new_prompt = click.edit(defn.system_prompt)
    if new_prompt is None or new_prompt.strip() == defn.system_prompt.strip():
        console.print("[dim]No changes.[/dim]")
        return

    cloned = api.clone_agent(defn.id, {"name": defn.name, "system_prompt": new_prompt.strip()})
    console.print(f"[bold green]Updated:[/bold green] {cloned.name} ({cloned.id})")
    console.print(f"[dim]Previous version: {defn.id[:12]}[/dim]")


@forge.command("export")
@click.argument("identifier")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
def export_agent(identifier: str, output: str | None) -> None:
    """Export an agent definition to a .agent.json file.

    Exports name, system_prompt, tools, and permissions (no IDs or timestamps).

    Examples:

        swarm forge export code-reviewer

        swarm forge export code-reviewer -o ./my-agent.agent.json
    """
    console = Console()
    registry = get_registry()
    try:
        defn = registry.resolve_agent(identifier)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e

    data = {
        "name": defn.name,
        "system_prompt": defn.system_prompt,
        "tools": list(defn.tools),
        "permissions": list(defn.permissions),
    }
    out_path = Path(output) if output else Path.cwd() / f"{defn.name}.agent.json"
    out_path.write_text(json.dumps(data, indent=2) + "\n")
    console.print(f"[bold green]Exported:[/bold green] {out_path}")


@forge.command("import")
@click.argument("path", type=click.Path(exists=True))
def import_agent(path: str) -> None:
    """Import an agent definition from a .agent.json file.

    Examples:

        swarm forge import ./code-reviewer.agent.json
    """
    console = Console()
    api = get_forge()
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]Error: invalid JSON: {e}[/red]")
        raise SystemExit(1) from e

    name = data.get("name")
    system_prompt = data.get("system_prompt")
    if not name or not system_prompt:
        console.print("[red]Error: file must contain 'name' and 'system_prompt' fields.[/red]")
        raise SystemExit(1)

    defn = api.create_agent(
        name=name,
        system_prompt=system_prompt,
        tools=data.get("tools", []),
        permissions=data.get("permissions", []),
    )
    console.print(f"[bold green]Imported:[/bold green] {defn.name} ({defn.id})")
