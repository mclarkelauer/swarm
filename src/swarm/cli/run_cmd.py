"""Interactive plan execution command."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from swarm.plan.dag import get_ready_steps
from swarm.plan.parser import load_plan, validate_plan
from swarm.plan.run_log import RunLog, StepOutcome, load_run_log, write_run_log


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--completed", default="", help="Comma-separated completed step IDs to resume from.")
def run(path: str, completed: str) -> None:
    """Walk a plan's DAG interactively, step by step.

    Loads the plan, walks the DAG using dependency resolution, shows each
    step, pauses at checkpoints, and writes a run log.

    This does NOT spawn agents — it shows execution order and records
    user confirmations.

    Examples:

        swarm run plan_v1.json

        swarm run plan_v1.json --completed s1,s2
    """
    console = Console()
    plan_path = Path(path)
    p = load_plan(plan_path)

    errors = validate_plan(p)
    if errors:
        console.print(f"[red]Plan has {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise SystemExit(1)

    log_path = plan_path.parent / "run_log.json"
    completed_set = {s.strip() for s in completed.split(",") if s.strip()}

    # Resume from existing run log if present and no explicit --completed
    if not completed_set and log_path.exists():
        try:
            existing_log = load_run_log(log_path)
            completed_set = existing_log.completed_step_ids
            if completed_set:
                console.print(
                    f"[dim]Resuming from run log ({len(completed_set)} steps completed).[/dim]"
                )
        except Exception:
            pass

    now = datetime.now(tz=UTC).isoformat()
    log = RunLog(
        plan_path=str(plan_path),
        plan_version=p.version,
        started_at=now,
        steps=[
            StepOutcome(step_id=sid, status="completed", started_at=now, finished_at=now)
            for sid in completed_set
        ],
    )
    write_run_log(log, log_path)

    all_ids = {s.id for s in p.steps}

    while True:
        ready = get_ready_steps(p, completed_set)

        if not ready and completed_set >= all_ids:
            log.status = "completed"
            log.finished_at = datetime.now(tz=UTC).isoformat()
            write_run_log(log, log_path)
            console.print("[bold green]Plan complete![/bold green]")
            break

        if not ready:
            log.status = "paused"
            write_run_log(log, log_path)
            console.print("[yellow]No steps are ready. Check dependencies.[/yellow]")
            break

        # Display ready steps
        table = Table(title="Ready Steps")
        table.add_column("Step", style="bold")
        table.add_column("Type")
        table.add_column("Agent")
        table.add_column("Prompt", max_width=60)
        for step in ready:
            table.add_row(step.id, step.type, step.agent_type or "-", step.prompt[:60])
        console.print(table)

        for step in ready:
            step_start = datetime.now(tz=UTC).isoformat()

            if step.type == "checkpoint":
                msg = step.checkpoint_config.message if step.checkpoint_config else step.prompt
                console.print(f"\n[bold yellow]Checkpoint:[/bold yellow] {msg}")
                if not click.confirm("Continue?"):
                    outcome = StepOutcome(
                        step_id=step.id,
                        status="skipped",
                        started_at=step_start,
                        finished_at=datetime.now(tz=UTC).isoformat(),
                        message="User declined checkpoint",
                    )
                    log.steps.append(outcome)
                    log.status = "paused"
                    log.finished_at = datetime.now(tz=UTC).isoformat()
                    write_run_log(log, log_path)
                    console.print("[yellow]Paused at checkpoint.[/yellow]")
                    return

            console.print(f"\n[bold cyan]{step.id}[/bold cyan] [{step.type}]")
            if step.agent_type:
                console.print(f"  Agent: {step.agent_type}")
            console.print(f"  Prompt: {step.prompt[:120]}")

            if not click.confirm(f"Mark step '{step.id}' as complete?"):
                outcome = StepOutcome(
                    step_id=step.id,
                    status="skipped",
                    started_at=step_start,
                    finished_at=datetime.now(tz=UTC).isoformat(),
                    message="User skipped",
                )
                log.steps.append(outcome)
                log.status = "paused"
                log.finished_at = datetime.now(tz=UTC).isoformat()
                write_run_log(log, log_path)
                console.print("[yellow]Paused.[/yellow]")
                return

            outcome = StepOutcome(
                step_id=step.id,
                status="completed",
                started_at=step_start,
                finished_at=datetime.now(tz=UTC).isoformat(),
            )
            log.steps.append(outcome)
            completed_set.add(step.id)
            write_run_log(log, log_path)
