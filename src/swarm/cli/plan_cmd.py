"""CLI commands for plan management."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from swarm.plan._paths import resolve_plans_dir as _resolve_plans_dir
from swarm.plan.dag import detect_cycles, get_ready_steps
from swarm.plan.models import Plan
from swarm.plan.parser import load_plan, save_plan, validate_plan
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
    target = _resolve_plans_dir(plans_dir)
    versions = list_versions(target)
    if not versions:
        console.print(f"[dim]No plans found in {target}[/dim]")
        return
    table = Table(title=f"Plans in {target}")
    table.add_column("Version", style="bold")
    table.add_column("File")
    table.add_column("Goal", max_width=50)
    table.add_column("Steps", justify="right")
    table.add_column("Modified")
    for v in versions:
        path = target / f"plan_v{v}.json"
        try:
            p = load_plan(path)
            mtime = datetime.fromtimestamp(
                path.stat().st_mtime, tz=UTC
            ).strftime("%Y-%m-%d %H:%M")
            table.add_row(str(v), path.name, p.goal[:50], str(len(p.steps)), mtime)
        except Exception:
            table.add_row(str(v), path.name, "?", "?", "?")
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


def _render_plan_tree(p: Plan, console: Console) -> None:
    """Render a plan as a Rich Tree (shared by show and create --dry-run)."""
    tree = Tree(f"[bold]{p.goal}[/bold]")
    for step in p.steps:
        deps = f" [dim](after: {', '.join(step.depends_on)})[/dim]" if step.depends_on else ""
        label = f"[cyan]{step.id}[/cyan] [{step.type}]{deps}"
        branch = tree.add(label)
        branch.add(f"[dim]{step.prompt[:80]}[/dim]")
        if step.agent_type:
            branch.add(f"agent: {step.agent_type}")
    console.print(tree)


@plan.command()
@click.option("--goal", required=True, help="The plan's goal description.")
@click.option(
    "--steps-file", required=True, type=click.Path(exists=True), help="JSON file with step definitions."
)
@click.option("--variables", default=None, type=click.Path(exists=True), help="JSON file with plan variables.")
@click.option("--dir", "plans_dir", default=".", help="Directory to save the plan in.")
@click.option("--dry-run", is_flag=True, help="Validate and show DAG without saving.")
def create(
    goal: str, steps_file: str, variables: str | None, plans_dir: str, dry_run: bool
) -> None:
    """Create a new execution plan from a steps file.

    Examples:

        swarm plan create --goal "Build API" --steps-file steps.json

        swarm plan create --goal "Build API" --steps-file steps.json --dry-run
    """
    console = Console()

    steps_data = json.loads(Path(steps_file).read_text())
    vars_data = json.loads(Path(variables).read_text()) if variables else {}

    plan_data = {"version": 1, "goal": goal, "steps": steps_data, "variables": vars_data}
    p = Plan.from_dict(plan_data)

    errors = validate_plan(p)
    try:
        detect_cycles(p)
    except ValueError as e:
        errors.append(str(e))

    if errors:
        console.print(f"[red]Plan has {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise SystemExit(1)

    if dry_run:
        _render_plan_tree(p, console)
        console.print()
        console.print("[yellow]Dry run — not saved.[/yellow]")
        return

    target = _resolve_plans_dir(plans_dir)
    saved_path = save_plan(p, target)
    console.print(f"[bold green]Saved:[/bold green] {saved_path} (version {p.version})")


@plan.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--completed", default="", help="Comma-separated list of completed step IDs.")
def resume(path: str, completed: str) -> None:
    """Show next steps for a partially-completed plan.

    Examples:

        swarm plan resume plan_v1.json --completed s1,s2
    """
    console = Console()
    p = load_plan(Path(path))
    completed_set = {s.strip() for s in completed.split(",") if s.strip()}

    ready = get_ready_steps(p, completed_set)
    all_ids = {s.id for s in p.steps}

    if not ready and completed_set >= all_ids:
        console.print("[bold green]Plan complete.[/bold green]")
        return

    if not ready:
        console.print("[yellow]No steps are ready. Check completed IDs.[/yellow]")
        return

    table = Table(title="Ready Steps")
    table.add_column("Step", style="bold")
    table.add_column("Type")
    table.add_column("Agent")
    table.add_column("Prompt", max_width=60)
    table.add_column("Depends On", style="dim")
    for step in ready:
        table.add_row(
            step.id,
            step.type,
            step.agent_type or "-",
            step.prompt[:60],
            ", ".join(step.depends_on) if step.depends_on else "-",
        )
    console.print(table)
