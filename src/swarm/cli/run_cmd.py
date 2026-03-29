"""Interactive plan execution command."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from swarm.plan.dag import get_ready_steps
from swarm.plan.models import Plan, PlanStep
from swarm.plan.parser import load_plan, validate_plan
from swarm.plan.run_log import RunLog, StepOutcome, load_run_log, write_run_log

_STEP_TYPE_COLORS: dict[str, str] = {
    "task": "cyan",
    "checkpoint": "yellow",
    "loop": "magenta",
}


def _compute_waves(plan: Plan) -> list[list[PlanStep]]:
    """Return steps grouped into parallel execution waves.

    Wave N contains every step whose dependencies are all satisfied by
    the steps in waves 0 … N-1.
    """
    waves: list[list[PlanStep]] = []
    completed: set[str] = set()
    remaining = {s.id for s in plan.steps}

    while remaining:
        wave = get_ready_steps(plan, completed)
        # get_ready_steps only returns steps not already completed; filter to
        # those still unassigned to a wave (should always be the same set here
        # since completed tracks exactly the assigned steps).
        wave = [s for s in wave if s.id in remaining]
        if not wave:
            # Shouldn't happen with a valid, acyclic plan — guard against it.
            break
        waves.append(wave)
        for s in wave:
            completed.add(s.id)
            remaining.discard(s.id)

    return waves


@click.command()
@click.argument("path", type=click.Path(), required=False, default=None)
@click.option("--latest", is_flag=True, help="Auto-select the highest version plan in cwd.")
@click.option("--completed", default="", help="Comma-separated completed step IDs to resume from.")
@click.option("--dry-run", is_flag=True, help="Print execution wave table and exit without prompting.")
def run(path: str | None, latest: bool, completed: str, dry_run: bool) -> None:
    """Walk a plan's DAG interactively, step by step.

    Loads the plan, walks the DAG using dependency resolution, shows each
    step, pauses at checkpoints, and writes a run log.

    This does NOT spawn agents — it shows execution order and records
    user confirmations.

    Examples:

        swarm run plan_v1.json

        swarm run --latest

        swarm run plan_v1.json --completed s1,s2

        swarm run plan_v1.json --dry-run
    """
    console = Console()

    if path is None and not latest:
        console.print("[red]Error: provide a plan path or use --latest.[/red]")
        raise SystemExit(1)

    if latest:
        from swarm.plan.versioning import list_versions

        cwd = Path.cwd()
        versions = list_versions(cwd)
        if not versions:
            console.print("[red]Error: no plan_v*.json files found in current directory.[/red]")
            raise SystemExit(1)
        plan_path = cwd / f"plan_v{versions[-1]}.json"
    else:
        plan_path = Path(path)  # type: ignore[arg-type]
        if not plan_path.exists():
            console.print(f"[red]Error: {plan_path} does not exist.[/red]")
            raise SystemExit(1)

    p = load_plan(plan_path)

    errors = validate_plan(p)
    if errors:
        console.print(f"[red]Plan has {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise SystemExit(1)

    if dry_run:
        waves = _compute_waves(p)

        table = Table(title="Execution Plan (dry-run)", show_lines=True)
        table.add_column("Wave", style="bold", justify="right")
        table.add_column("Step ID", style="bold")
        table.add_column("Agent")
        table.add_column("Type")
        table.add_column("Spawn Mode")

        for wave_num, wave_steps in enumerate(waves, start=1):
            for step in wave_steps:
                color = _STEP_TYPE_COLORS.get(step.type, "white")
                table.add_row(
                    str(wave_num),
                    step.id,
                    step.agent_type or "-",
                    f"[{color}]{step.type}[/{color}]",
                    step.spawn_mode,
                )

        console.print(table)

        total_steps = sum(len(w) for w in waves)
        max_parallel = max((len(w) for w in waves), default=0)
        console.print(
            f"[bold]{total_steps} step(s) in {len(waves)} wave(s).[/bold] "
            f"Up to [bold]{max_parallel}[/bold] step(s) can run in parallel."
        )
        return

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
