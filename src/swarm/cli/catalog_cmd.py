"""CLI commands for the built-in base agent catalog.

``swarm catalog``        — list all base agents grouped by domain
``swarm catalog search`` — search by name/description/tags
``swarm catalog show``   — full details of one base agent
``swarm catalog seed``   — manually trigger catalog seeding
"""

from __future__ import annotations

from typing import Any, cast

import click
from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table

from swarm.catalog import ALL_BASE_AGENTS
from swarm.catalog.seed import _catalog_id, seed_base_agents
from swarm.cli._helpers import get_registry

# ---------------------------------------------------------------------------
# Domain grouping
# ---------------------------------------------------------------------------

# These tag values are the canonical domain labels used in the catalog files.
_DOMAIN_ORDER = ["technical", "general", "business"]
_DOMAIN_LABELS: dict[str, str] = {
    "technical": "Technical",
    "general": "General",
    "business": "Business",
}


def _agent_domain(spec: dict[str, Any]) -> str:
    """Return the primary domain tag for a catalog agent spec.

    Falls back to ``"general"`` if no known domain tag is present.

    Args:
        spec: Raw agent spec dict from the catalog.

    Returns:
        One of ``"technical"``, ``"general"``, or ``"business"``.
    """
    tags: list[str] = list(spec.get("tags", []))
    for domain in _DOMAIN_ORDER:
        if domain in tags:
            return domain
    return "general"


def _search_agent(spec: dict[str, Any], query: str) -> bool:
    """Return ``True`` if *query* matches the spec's name, description, or tags.

    Case-insensitive substring match.

    Args:
        spec: Raw agent spec dict.
        query: Search string.

    Returns:
        Whether the agent matches the query.
    """
    q = query.lower()
    name = str(spec.get("name", "")).lower()
    description = str(spec.get("description", "")).lower()
    tags = " ".join(str(t) for t in spec.get("tags", [])).lower()
    return q in name or q in description or q in tags


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.pass_context
def catalog(ctx: click.Context) -> None:
    """Browse and seed the built-in base agent catalog.

    Run without a subcommand to list all base agents grouped by domain.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_catalog)


# ---------------------------------------------------------------------------
# swarm catalog (list)
# ---------------------------------------------------------------------------


@catalog.command("list")
def list_catalog() -> None:
    """List all base agents grouped by domain."""
    console = Console()

    # Group agents by domain, preserving catalog order within each group.
    groups: dict[str, list[dict[str, Any]]] = {d: [] for d in _DOMAIN_ORDER}
    for spec in ALL_BASE_AGENTS:
        domain = _agent_domain(spec)
        groups.setdefault(domain, []).append(spec)

    total = len(ALL_BASE_AGENTS)
    console.print(f"\n[bold]Base Agent Catalog[/bold] — {total} agents\n")
    console.print("[dim]Clone any agent with: swarm registry clone <name> --name <new-name>[/dim]")
    console.print("")

    for domain in _DOMAIN_ORDER:
        agents = groups.get(domain, [])
        if not agents:
            continue

        label = _DOMAIN_LABELS.get(domain, domain.title())
        console.print(Rule(f"[bold]{label}[/bold] ({len(agents)})"))

        table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
        table.add_column("Name", style="bold cyan", min_width=24)
        table.add_column("Description", max_width=60)
        table.add_column("Tags", style="dim", max_width=36)

        for spec in agents:
            name = str(spec.get("name", ""))
            description = str(spec.get("description", ""))
            tags_raw: list[str] = [
                t for t in cast(list[str], spec.get("tags", []))
                if t not in _DOMAIN_ORDER and t != "base"
            ]
            tags_str = ", ".join(tags_raw[:4])
            if len(tags_raw) > 4:
                tags_str += f", +{len(tags_raw) - 4}"
            table.add_row(name, description, tags_str)

        console.print(table)
        console.print("")

    console.print(
        "[dim]Use [bold]swarm catalog show <name>[/bold] for full details "
        "and specialization guidance.[/dim]"
    )


# ---------------------------------------------------------------------------
# swarm catalog search QUERY
# ---------------------------------------------------------------------------


@catalog.command()
@click.argument("query")
def search(query: str) -> None:
    """Search base agents by name, description, or tags.

    Examples:

        swarm catalog search "code review"

        swarm catalog search testing

        swarm catalog search security
    """
    console = Console()

    matches = [spec for spec in ALL_BASE_AGENTS if _search_agent(spec, query)]

    if not matches:
        console.print(f"[dim]No base agents matching '{query}'.[/dim]")
        console.print("[dim]Try a broader term or run [bold]swarm catalog list[/bold].[/dim]")
        return

    console.print(f"\n[bold]Base agents matching '{query}'[/bold] — {len(matches)} found\n")

    table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
    table.add_column("Name", style="bold cyan", min_width=24)
    table.add_column("Domain", style="dim", min_width=10)
    table.add_column("Description", max_width=60)
    table.add_column("Tags", style="dim", max_width=36)

    for spec in matches:
        name = str(spec.get("name", ""))
        domain = _DOMAIN_LABELS.get(_agent_domain(spec), "")
        description = str(spec.get("description", ""))
        tags_raw: list[str] = [
            t for t in cast(list[str], spec.get("tags", []))
            if t not in _DOMAIN_ORDER and t != "base"
        ]
        tags_str = ", ".join(tags_raw[:5])
        table.add_row(name, domain, description, tags_str)

    console.print(table)
    console.print(
        "\n[dim]Run [bold]swarm catalog show <name>[/bold] for full details.[/dim]"
    )


# ---------------------------------------------------------------------------
# swarm catalog show NAME
# ---------------------------------------------------------------------------


@catalog.command()
@click.argument("name")
def show(name: str) -> None:
    """Show full details of a base agent including specialization notes.

    NAME is the catalog agent name, e.g. ``code-researcher``.

    Examples:

        swarm catalog show code-researcher

        swarm catalog show security-auditor
    """
    console = Console()

    # Find the spec — exact match first, then case-insensitive prefix
    spec: dict[str, Any] | None = None
    for s in ALL_BASE_AGENTS:
        if str(s.get("name", "")) == name:
            spec = s
            break
    if spec is None:
        name_lower = name.lower()
        for s in ALL_BASE_AGENTS:
            if str(s.get("name", "")).lower().startswith(name_lower):
                spec = s
                break
    if spec is None:
        console.print(f"[red]No catalog agent named '{name}'.[/red]")
        console.print("[dim]Run [bold]swarm catalog list[/bold] to see all agents.[/dim]")
        raise SystemExit(1)

    agent_name = str(spec.get("name", ""))
    agent_id = _catalog_id(agent_name)
    domain = _DOMAIN_LABELS.get(_agent_domain(spec), "")
    description = str(spec.get("description", ""))
    system_prompt = str(spec.get("system_prompt", ""))
    tools: list[str] = list(cast(list[str], spec.get("tools", [])))
    tags: list[str] = list(cast(list[str], spec.get("tags", [])))
    notes = str(spec.get("notes", ""))
    model = str(spec.get("model", ""))

    # Check registry status
    registry = get_registry()
    in_registry = registry.get(agent_id) is not None

    console.print("")
    console.print(f"[bold cyan]{agent_name}[/bold cyan]  [dim]{domain}[/dim]")
    console.print(f"[dim]Catalog ID: {agent_id[:12]}...[/dim]")
    console.print(f"[dim]In registry: {'yes' if in_registry else 'no (run swarm catalog seed)'}[/dim]")
    console.print("")

    console.print("[bold]Description[/bold]")
    console.print(Padding(description, (0, 0, 1, 2)))

    if model:
        console.print(f"[bold]Recommended model:[/bold] {model}")
        console.print("")

    if tools:
        console.print(f"[bold]Tools:[/bold] {', '.join(tools)}")
        console.print("")

    if tags:
        display_tags = [t for t in tags if t not in ("base",)]
        console.print(f"[bold]Tags:[/bold] {', '.join(display_tags)}")
        console.print("")

    console.print(Rule("[bold]System Prompt[/bold]"))
    console.print(Padding(system_prompt, (1, 2)))

    if notes:
        console.print("")
        console.print(Rule("[bold]Specialization Notes[/bold]"))
        console.print(Padding(f"[italic]{notes}[/italic]", (1, 2)))

    console.print("")
    console.print(
        f"[dim]Clone this agent: "
        f"[bold]swarm registry clone {agent_name} --name my-{agent_name}[/bold][/dim]"
    )


# ---------------------------------------------------------------------------
# swarm catalog seed
# ---------------------------------------------------------------------------


@catalog.command()
@click.option("--quiet", "-q", is_flag=True, help="Suppress output on no changes.")
def seed(quiet: bool) -> None:
    """Seed the registry with all built-in base agents.

    This runs automatically on session launch.  Use this command to
    manually trigger a re-seed after upgrading Swarm.

    Agents that already exist and are unchanged are left untouched.
    Updated catalog agents have their system_prompt refreshed, and any
    clones are flagged with a [PARENT UPDATED] notice in their notes.
    """
    console = Console()
    registry = get_registry()

    with console.status("[bold blue]Seeding catalog...[/bold blue]"):
        summary = seed_base_agents(registry)

    created = summary["created"]
    updated = summary["updated"]
    unchanged = summary["unchanged"]

    has_changes = bool(created or updated)

    if has_changes or not quiet:
        console.print("")

    if created:
        console.print(f"[bold green]Created[/bold green] {len(created)} agents:")
        for name in created:
            console.print(f"  + {name}")
        console.print("")

    if updated:
        console.print(f"[bold yellow]Updated[/bold yellow] {len(updated)} agents (system_prompt changed):")
        for name in updated:
            console.print(f"  ~ {name}")
        console.print(
            "\n  [dim]Clones of updated agents have a [PARENT UPDATED] notice in their notes.[/dim]"
        )
        console.print("")

    if not has_changes and not quiet:
        console.print(
            f"[dim]Catalog up to date — {len(unchanged)} agents unchanged.[/dim]"
        )

    if has_changes:
        total = len(created) + len(updated) + len(unchanged)
        console.print(
            f"[dim]Registry now contains {total} catalog agents.[/dim]"
        )
