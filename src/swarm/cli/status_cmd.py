"""swarm status command — display run log for a plan execution."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.table import Table

from swarm.plan.run_log import RunLog, StepOutcome, load_run_log

if TYPE_CHECKING:
    from swarm.plan.models import Plan, PlanStep


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _format_duration(started_at: str, finished_at: str) -> str:
    """Compute human-readable duration between two ISO timestamps."""
    start = _parse_iso(started_at)
    end = _parse_iso(finished_at)
    if start is None or end is None:
        return "-"
    delta = end - start
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "-"
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"


def _status_color(status: str) -> str:
    """Return Rich color markup for a status string."""
    colors = {
        "running": "blue",
        "completed": "green",
        "paused": "yellow",
        "failed": "red",
        "skipped": "dim",
    }
    color = colors.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def _build_step_meta(log: RunLog) -> dict[str, dict[str, str]]:
    """Load the plan referenced by the log and build a step metadata dict.

    Returns a mapping of step_id -> {"type": ..., "agent_type": ...}.
    Returns an empty dict if the plan file cannot be loaded.
    """
    plan_path = Path(log.plan_path)
    if not plan_path.exists():
        return {}
    try:
        from swarm.plan.parser import load_plan

        plan = load_plan(plan_path)
        return {
            s.id: {"type": s.type, "agent_type": s.agent_type or "-"}
            for s in plan.steps
        }
    except Exception:
        return {}


def _load_plan_for_diagnose(log: RunLog) -> Plan | None:
    """Attempt to load the plan referenced by the run log.

    Returns the Plan or None if the file is missing or unreadable.
    """
    plan_path = Path(log.plan_path)
    if not plan_path.exists():
        return None
    try:
        from swarm.plan.parser import load_plan

        return load_plan(plan_path)
    except Exception:
        return None


def _find_blocked_steps(
    failed_step_id: str,
    all_plan_steps: list[PlanStep],
    completed_ids: set[str],
) -> list[str]:
    """Return IDs of steps whose depends_on includes failed_step_id and are not completed."""
    blocked: list[str] = []
    for step in all_plan_steps:
        if failed_step_id in step.depends_on and step.id not in completed_ids:
            blocked.append(step.id)
    return blocked


def _print_diagnose(
    console: Console,
    log: RunLog,
) -> None:
    """Print failure diagnosis after the status table."""
    if log.status in ("completed", "running"):
        console.print("[dim]No failures to diagnose.[/dim]")
        return

    # log.status is 'failed' or 'paused'
    failed_outcomes = [s for s in log.steps if s.status in ("failed", "skipped")]

    if not failed_outcomes:
        console.print(
            "[yellow]Run is paused but no failures recorded. "
            "Check checkpoint status.[/yellow]"
        )
        return

    plan = _load_plan_for_diagnose(log)
    completed_ids = log.completed_step_ids

    console.print()
    console.print("[bold]Failure Diagnosis[/bold]")
    console.print()

    if plan is None:
        # No plan available — show basic info from run log only
        console.print(
            "[yellow]Plan file not found — showing basic info from run log only.[/yellow]"
        )
        console.print()
        for outcome in failed_outcomes:
            _print_failed_step_basic(console, outcome)
        return

    # Build a lookup from step id to PlanStep
    plan_step_map: dict[str, PlanStep] = {s.id: s for s in plan.steps}

    for outcome in failed_outcomes:
        plan_step = plan_step_map.get(outcome.step_id)
        agent_type = plan_step.agent_type if plan_step else "-"
        on_failure = plan_step.on_failure if plan_step else "stop"

        # Header line for this failed step
        console.print(
            f"[red]FAILED:[/red] [bold]{outcome.step_id}[/bold]"
            f"  agent={agent_type}"
        )

        if outcome.message:
            console.print(f"  [dim]Error:[/dim] {outcome.message}")

        # Blocked downstream steps
        blocked = _find_blocked_steps(outcome.step_id, plan.steps, completed_ids)
        if blocked:
            console.print("  [yellow]Blocked downstream steps:[/yellow]")
            for dep_id in blocked:
                console.print(f"    - {dep_id}")

        # Suggested next actions based on on_failure strategy
        console.print(f"  [dim]on_failure strategy:[/dim] {on_failure}")
        _print_suggestion(console, outcome.step_id, on_failure)
        console.print()


def _print_failed_step_basic(console: Console, outcome: StepOutcome) -> None:
    """Print a failed step with no plan context available."""
    console.print(
        f"[red]FAILED:[/red] [bold]{outcome.step_id}[/bold]"
        f"  (status={outcome.status})"
    )
    if outcome.message:
        console.print(f"  [dim]Error:[/dim] {outcome.message}")
    # Default suggestion when plan is missing
    _print_suggestion(console, outcome.step_id, "stop")
    console.print()


def _print_suggestion(console: Console, step_id: str, on_failure: str) -> None:
    """Print the suggested next action for a failed step."""
    if on_failure == "stop":
        console.print(
            f"  [dim]-> Consider: plan_amend to insert a fix step after '{step_id}'[/dim]"
        )
    elif on_failure == "retry":
        console.print(
            "  [dim]-> Step was set to retry — check if max retries were reached[/dim]"
        )
    elif on_failure == "skip":
        console.print(
            "  [dim]-> Step was skipped — downstream steps may have missing inputs[/dim]"
        )
    else:
        console.print(
            f"  [dim]-> Unknown on_failure strategy '{on_failure}'[/dim]"
        )


@click.command()
@click.option(
    "--log-file",
    default="run_log.json",
    show_default=True,
    help="Path to the run log JSON file.",
)
@click.option(
    "--diagnose",
    is_flag=True,
    help="Show failure diagnosis for paused/failed runs.",
)
def status(log_file: str, diagnose: bool) -> None:
    """Show execution status from a run log.

    Reads run_log.json (or the file given by --log-file) and prints a
    summary table of step progress, durations, and statuses.

    Pass --diagnose to see failure analysis and suggested next actions
    for paused or failed runs.

    Examples:

        swarm status

        swarm status --log-file /path/to/run_log.json

        swarm status --diagnose
    """
    console = Console()
    log_path = Path(log_file)

    if not log_path.exists():
        console.print(f"[dim]No run log found at {log_path}.[/dim]")
        return

    try:
        log: RunLog = load_run_log(log_path)
    except Exception as exc:
        console.print(f"[red]Error reading run log: {exc}[/red]")
        raise SystemExit(1) from exc

    # ---- Header ----------------------------------------------------------------
    completed_count = sum(1 for s in log.steps if s.status == "completed")

    # Try to get the real plan step count for accurate progress display.
    plan_total: int | None = None
    plan_path = Path(log.plan_path)
    if plan_path.exists():
        try:
            from swarm.plan.parser import load_plan

            plan_total = len(load_plan(plan_path).steps)
        except Exception:
            pass
    total_display = plan_total if plan_total is not None else len(log.steps)

    console.print(f"[bold]Plan:[/bold]    {log.plan_path}")
    console.print(f"[bold]Version:[/bold] {log.plan_version}")
    console.print(f"[bold]Status:[/bold]  {_status_color(log.status)}")
    console.print(f"[bold]Progress:[/bold] {completed_count}/{total_display} steps complete")
    console.print()

    if not log.steps:
        console.print("[dim]No step outcomes recorded yet.[/dim]")
        if diagnose:
            console.print()
            _print_diagnose(console, log)
        return

    # ---- Cross-reference plan for type/agent info ------------------------------
    step_meta = _build_step_meta(log)

    # ---- Table -----------------------------------------------------------------
    table = Table(title="Step Outcomes")
    table.add_column("Step ID", style="bold")
    table.add_column("Type")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Duration", justify="right")
    table.add_column("Message")

    for outcome in log.steps:
        meta = step_meta.get(outcome.step_id, {})
        step_type = meta.get("type", "-")
        agent_type = meta.get("agent_type", "-")
        duration = _format_duration(outcome.started_at, outcome.finished_at)

        table.add_row(
            outcome.step_id,
            step_type,
            agent_type,
            _status_color(outcome.status),
            duration,
            outcome.message or "-",
        )

    console.print(table)

    # ---- Diagnose (optional) ---------------------------------------------------
    if diagnose:
        console.print()
        _print_diagnose(console, log)
