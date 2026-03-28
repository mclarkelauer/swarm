"""Sync project-local agent definitions into the registry."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

from swarm.cli._helpers import get_forge


@click.command()
@click.option("--dir", "project_dir", default=".", help="Project directory with .swarm/agents/.")
def sync(project_dir: str) -> None:
    """Import project-local agent definitions into the registry.

    Scans ``.swarm/agents/*.agent.json`` in the project directory and
    registers any that aren't already in the registry.

    Examples:

        swarm sync

        swarm sync --dir /path/to/project
    """
    console = Console()
    agents_dir = Path(project_dir) / ".swarm" / "agents"

    if not agents_dir.is_dir():
        console.print(f"[dim]No .swarm/agents/ directory in {Path(project_dir).resolve()}[/dim]")
        return

    api = get_forge()
    imported = 0
    skipped = 0

    for path in sorted(agents_dir.glob("*.agent.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            console.print(f"[yellow]Skipping malformed: {path.name}[/yellow]")
            continue

        name = data.get("name")
        if not name:
            console.print(f"[yellow]Skipping (no name): {path.name}[/yellow]")
            continue

        # Check if already registered
        existing = api.suggest_agent(name)
        if any(e.name == name for e in existing):
            console.print(f"[dim]Already registered: {name}[/dim]")
            skipped += 1
            continue

        api.create_agent(
            name=name,
            system_prompt=data.get("system_prompt", ""),
            tools=data.get("tools", []),
            permissions=data.get("permissions", []),
        )
        console.print(f"[green]Imported: {name}[/green]")
        imported += 1

    console.print(f"\n[bold]{imported} imported, {skipped} skipped.[/bold]")
