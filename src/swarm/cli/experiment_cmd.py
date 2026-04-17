"""CLI commands for agent A/B experiments."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from swarm.cli._helpers import open_experiments


@click.group()
def experiment() -> None:
    """Manage A/B experiments comparing agent variants."""


@experiment.command("create")
@click.option("--name", required=True, help="Unique experiment name.")
@click.option("--agent-a", required=True, help="Variant A (control) agent name.")
@click.option("--agent-b", required=True, help="Variant B (treatment) agent name.")
@click.option(
    "--traffic-pct",
    default=50.0,
    show_default=True,
    type=float,
    help="Percentage of traffic routed to variant B (0-100).",
)
@click.option("--description", default="", help="Human-readable description.")
def create_experiment(
    name: str,
    agent_a: str,
    agent_b: str,
    traffic_pct: float,
    description: str,
) -> None:
    """Create a new A/B experiment."""
    with open_experiments() as api:
        try:
            result = api.create(
                name=name,
                agent_a=agent_a,
                agent_b=agent_b,
                traffic_pct=traffic_pct,
                description=description,
            )
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc
    click.echo(f"Created experiment '{result['name']}' ({result['id']})")


@experiment.command("list")
@click.option(
    "--status",
    default="",
    help="Filter by status (active or ended). Empty = all.",
)
def list_experiments(status: str) -> None:
    """List experiments, optionally filtered by status."""
    with open_experiments() as api:
        experiments = api.list_experiments(status=status)
    console = Console()
    if not experiments:
        console.print("[dim]No experiments found.[/dim]")
        return
    table = Table(title="Experiments")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Variant A")
    table.add_column("Variant B")
    table.add_column("Traffic %", justify="right")
    table.add_column("Status")
    for exp in experiments:
        table.add_row(
            exp["name"],
            exp["id"][:12],
            exp["agent_a"],
            exp["agent_b"],
            f"{exp['traffic_pct']:.1f}",
            exp["status"],
        )
    console.print(table)


@experiment.command("results")
@click.argument("experiment_name")
def results(experiment_name: str) -> None:
    """Show aggregated results for an experiment."""
    with open_experiments() as api:
        try:
            data = api.get_results(experiment_name)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc
    console = Console()
    console.print(f"[bold]Experiment:[/bold] {data['name']}")
    console.print(f"[bold]Status:[/bold] {data['status']}")
    if data.get("description"):
        console.print(f"[bold]Description:[/bold] {data['description']}")
    table = Table(title="Variant performance")
    table.add_column("Variant", style="bold")
    table.add_column("Agent")
    table.add_column("Runs", justify="right")
    table.add_column("Successes", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Success rate", justify="right")
    table.add_column("Avg duration (s)", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right")
    for label in ("A", "B"):
        v = data["variants"][label]
        table.add_row(
            label,
            v["agent"],
            str(v["total_runs"]),
            str(v["successes"]),
            str(v["failures"]),
            f"{v['success_rate']:.2%}",
            f"{v['avg_duration_secs']:.2f}",
            str(v["total_tokens"]),
            f"{v['total_cost_usd']:.4f}",
        )
    console.print(table)
    winner = data.get("winner")
    if winner is None:
        console.print("[dim]Winner: not yet determined (need data on both variants).[/dim]")
    elif winner == "tie":
        console.print("[bold]Winner:[/bold] tie")
    else:
        console.print(f"[bold]Winner:[/bold] {winner}")


@experiment.command("end")
@click.argument("experiment_name")
def end(experiment_name: str) -> None:
    """End an active experiment."""
    with open_experiments() as api:
        ended = api.end_experiment(experiment_name)
    if ended:
        click.echo(f"Ended experiment '{experiment_name}'")
    else:
        click.echo(
            f"No active experiment named '{experiment_name}' found.",
            err=True,
        )
        raise SystemExit(1)


@experiment.command("assign")
@click.argument("experiment_name")
def assign(experiment_name: str) -> None:
    """Assign a variant for one invocation of an experiment.

    Mirrors the ``experiment_assign_variant`` MCP tool so orchestrators
    operating from a shell can route traffic without an active Claude
    session.  Prints the resolved ``variant`` (``A`` or ``B``) and the
    selected agent name on stdout.
    """
    with open_experiments() as api:
        try:
            agent, variant = api.resolve_variant(experiment_name)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc
    click.echo(f"{variant}\t{agent}")


@experiment.command("record")
@click.argument("experiment_name")
@click.option("--variant", required=True, type=click.Choice(["A", "B"]), help="Variant to record against.")
@click.option(
    "--success/--failure",
    default=True,
    help="Whether the run succeeded (default) or failed.",
)
@click.option("--duration-secs", default=0.0, type=float, help="Step duration in seconds.")
@click.option("--tokens-used", default=0, type=int, help="Tokens consumed.")
@click.option("--cost-usd", default=0.0, type=float, help="Cost in USD.")
@click.option("--run-id", default="", help="Plan run identifier.")
@click.option("--step-id", default="", help="Step identifier.")
def record(
    experiment_name: str,
    variant: str,
    success: bool,
    duration_secs: float,
    tokens_used: int,
    cost_usd: float,
    run_id: str,
    step_id: str,
) -> None:
    """Record a result for an experiment variant."""
    with open_experiments() as api:
        try:
            result = api.record_result(
                experiment_name=experiment_name,
                variant=variant,
                success=success,
                duration_secs=duration_secs,
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                run_id=run_id,
                step_id=step_id,
            )
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc
    click.echo(
        f"Recorded {variant} result ({'success' if success else 'failure'}) "
        f"for '{experiment_name}' ({result['id']})"
    )
