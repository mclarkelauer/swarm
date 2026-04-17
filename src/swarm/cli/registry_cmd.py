"""CLI commands for the agent registry."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from swarm.cli._helpers import open_registry


@click.group()
def registry() -> None:
    """Manage agent definitions in the registry."""


@registry.command("list")
def list_agents() -> None:
    """List all registered agent definitions."""
    with open_registry() as api:
        agents = api.list_agents()
    console = Console()
    if not agents:
        console.print("[dim]No agents registered.[/dim]")
        return
    table = Table(title="Registered Agents")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Parent", style="dim", max_width=12)
    for a in agents:
        table.add_row(a.id[:12], a.name, a.source, (a.parent_id or "")[:12])
    console.print(table)


@registry.command()
@click.argument("query")
def search(query: str) -> None:
    """Search agent definitions by name or prompt."""
    with open_registry() as api:
        results = api.search(query)
    console = Console()
    if not results:
        console.print(f"[dim]No agents matching '{query}'.[/dim]")
        return
    table = Table(title=f"Agents matching '{query}'")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Prompt", max_width=60)
    table.add_column("Parent", style="dim", max_width=12)
    for a in results:
        table.add_row(a.name, a.id[:12], a.system_prompt[:60], (a.parent_id or "")[:12])
    console.print(table)


@registry.command()
@click.argument("identifier")
def inspect(identifier: str) -> None:
    """Show full details and provenance chain for an agent.

    IDENTIFIER can be an agent name or UUID.
    """
    with open_registry() as api:
        try:
            defn = api.resolve_agent(identifier)
            info = api.inspect(defn.id)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
    console = Console()
    console.print(f"[bold]Name:[/bold] {info['name']}")
    console.print(f"[bold]ID:[/bold] {info['id']}")
    console.print(f"[bold]Source:[/bold] {info['source']}")
    console.print(f"[bold]Prompt:[/bold] {info['system_prompt']}")
    console.print(f"[bold]Tools:[/bold] {info['tools']}")
    console.print(f"[bold]Permissions:[/bold] {info['permissions']}")
    chain: list[dict[str, str]] = info.get("provenance_chain", [])  # type: ignore[assignment]
    if chain:
        console.print("[bold]Provenance:[/bold]")
        for link in chain:
            console.print(f"  <- {link['name']} ({link['id'][:12]})")


@registry.command()
@click.argument("identifier")
def remove(identifier: str) -> None:
    """Remove an agent definition.

    IDENTIFIER can be an agent name or UUID.
    """
    with open_registry() as api:
        try:
            defn = api.resolve_agent(identifier)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
        api.remove(defn.id)
    click.echo(f"Removed agent {defn.name} ({defn.id})")


@registry.command()
@click.option("--name", required=True, help="Agent type name")
@click.option("--prompt", required=True, help="System prompt")
@click.option("--tools", default="", help="Comma-separated tools")
@click.option("--permissions", default="", help="Comma-separated permissions")
def create(name: str, prompt: str, tools: str, permissions: str) -> None:
    """Create a new agent definition."""
    with open_registry() as api:
        tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else []
        perm_list = [p.strip() for p in permissions.split(",") if p.strip()] if permissions else []
        d = api.create(name, prompt, tool_list, perm_list)
    click.echo(f"Created agent '{d.name}' ({d.id})")


@registry.command()
@click.argument("identifier")
@click.option("--name", required=True, help="New agent name")
@click.option("--prompt", default=None, help="Override system prompt")
@click.option("--tools", default=None, help="Override tools (comma-separated)")
def clone(identifier: str, name: str, prompt: str | None, tools: str | None) -> None:
    """Clone an agent definition with overrides.

    IDENTIFIER can be an agent name or UUID.
    """
    with open_registry() as api:
        overrides: dict[str, str | int | list[str]] = {"name": name}
        if prompt is not None:
            overrides["system_prompt"] = prompt
        if tools is not None:
            overrides["tools"] = [t.strip() for t in tools.split(",") if t.strip()]
        try:
            defn = api.resolve_agent(identifier)
            d = api.clone(defn.id, overrides)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from e
    click.echo(f"Cloned to '{d.name}' ({d.id})")
