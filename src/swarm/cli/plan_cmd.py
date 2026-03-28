"""CLI commands for plan management."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from swarm.plan.parser import load_plan, validate_plan
from swarm.plan.versioning import list_versions


@click.group()
def plan() -> None:
    """Manage execution plans."""


@plan.command()
@click.argument("path", type=click.Path(exists=True))
def validate(path: str) -> None:
    """Validate a plan JSON file."""
    console = Console()
    p = load_plan(Path(path))
    errors = validate_plan(p)
    if errors:
        console.print(f"[red]Plan has {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise SystemExit(1)
    console.print(f"[green]Plan is valid.[/green] {len(p.steps)} steps, goal: {p.goal}")


@plan.command("list")
@click.option("--dir", "plans_dir", default=".", help="Directory to scan for plans.")
def list_plans(plans_dir: str) -> None:
    """List plan versions in a directory."""
    console = Console()
    target = Path(plans_dir)
    versions = list_versions(target)
    if not versions:
        console.print(f"[dim]No plans found in {target}[/dim]")
        return
    table = Table(title=f"Plans in {target}")
    table.add_column("Version", style="bold")
    table.add_column("File")
    for v in versions:
        table.add_row(str(v), f"plan_v{v}.json")
    console.print(table)


@plan.command()
@click.argument("path", type=click.Path(exists=True))
def show(path: str) -> None:
    """Display a plan's structure and DAG."""
    console = Console()
    p = load_plan(Path(path))

    console.print(f"[bold]Goal:[/bold] {p.goal}")
    console.print(f"[bold]Version:[/bold] {p.version}")
    if p.variables:
        console.print(f"[bold]Variables:[/bold] {p.variables}")
    console.print()

    tree = Tree(f"[bold]{p.goal}[/bold]")
    for step in p.steps:
        deps = f" [dim](after: {', '.join(step.depends_on)})[/dim]" if step.depends_on else ""
        label = f"[cyan]{step.id}[/cyan] [{step.type}]{deps}"
        branch = tree.add(label)
        branch.add(f"[dim]{step.prompt[:80]}[/dim]")
        if step.agent_type:
            branch.add(f"agent: {step.agent_type}")
    console.print(tree)
