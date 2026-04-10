"""MCP tools for autonomous plan execution."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.errors import ExecutionError, PlanError
from swarm.mcp.instance import mcp
from swarm.plan.executor import execute_plan, init_run_state
from swarm.plan.parser import load_plan
from swarm.plan.run_log import load_run_log, write_run_log


@mcp.tool()
def plan_run(
    plan_path: str,
    run_log_path: str = "",
    artifacts_dir: str = "",
    max_steps: str = "0",
    dry_run: str = "false",
    resume: str = "true",
) -> str:
    """Start or resume autonomous plan execution.

    Loads the plan, initializes or resumes execution state, then enters
    the main execution loop.  Returns when the plan completes, a
    checkpoint is reached, ``max_steps`` is hit, or an unrecoverable
    failure occurs.

    Args:
        plan_path: Path to the plan JSON file.
        run_log_path: Path for the run log (default: ``<plan_dir>/run_log.json``).
        artifacts_dir: Directory for step output artifacts
            (default: ``<plan_dir>/artifacts``).
        max_steps: Maximum steps to execute before pausing
            (default: ``"0"`` = unlimited).
        dry_run: ``"true"`` to preview execution order without launching
            agents (default: ``"false"``).
        resume: ``"true"`` to resume from an existing run log if present
            (default: ``"true"``).

    Returns:
        JSON object with ``status``, ``steps_executed``, ``steps_remaining``,
        ``completed_step_ids``, ``failed_step_ids``, ``run_log_path``,
        ``checkpoint_message``, and ``errors``.
    """
    p_path = Path(plan_path)
    if not p_path.exists():
        return json.dumps({"error": f"Plan file not found: {plan_path}"})

    try:
        plan = load_plan(p_path)
    except (json.JSONDecodeError, KeyError, PlanError, OSError) as exc:
        return json.dumps({"error": f"Failed to load plan: {exc}"})

    plan_dir = p_path.parent

    # Resolve paths
    log_path = Path(run_log_path) if run_log_path else plan_dir / "run_log.json"
    art_dir = Path(artifacts_dir) if artifacts_dir else plan_dir / "artifacts"

    max_s = int(max_steps)

    # Dry run: just preview the execution order
    if dry_run.lower() == "true":
        from swarm.plan.dag import get_ready_steps

        steps_order: list[dict[str, str]] = []
        completed: set[str] = set()
        all_ids = {s.id for s in plan.steps}
        wave = 0

        while completed < all_ids:
            ready = get_ready_steps(plan, completed)
            if not ready:
                break
            wave += 1
            for s in ready:
                steps_order.append({
                    "wave": str(wave),
                    "step_id": s.id,
                    "type": s.type,
                    "agent_type": s.agent_type,
                    "spawn_mode": s.spawn_mode,
                })
                completed.add(s.id)

        return json.dumps({
            "dry_run": True,
            "waves": wave,
            "steps": steps_order,
            "total_steps": len(plan.steps),
        })

    # Clear existing run log if not resuming
    if resume.lower() != "true" and log_path.exists():
        log_path.unlink()

    try:
        run_state = init_run_state(plan, p_path, art_dir, log_path)
    except ExecutionError as exc:
        return json.dumps({"error": str(exc)})

    try:
        result = execute_plan(run_state, max_steps=max_s)
    except ExecutionError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps(result)


@mcp.tool()
def plan_run_status(run_log_path: str) -> str:
    """Query the status of a running or completed plan execution.

    Args:
        run_log_path: Path to the run log file.

    Returns:
        JSON object with ``status``, ``progress``, ``last_completed_step``,
        ``next_ready_steps``, and ``checkpoint_message``.
    """
    log_p = Path(run_log_path)
    if not log_p.exists():
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    try:
        log = load_run_log(log_p)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        return json.dumps({"error": f"Failed to load run log: {exc}"})

    completed = sum(1 for s in log.steps if s.status == "completed")
    failed = sum(1 for s in log.steps if s.status == "failed")
    skipped = sum(1 for s in log.steps if s.status == "skipped")

    # Determine total from the plan file
    total = 0
    next_ready: list[str] = []
    try:
        plan = load_plan(Path(log.plan_path))
        total = len(plan.steps)
        completed_ids = {s.step_id for s in log.steps if s.status == "completed"}
        skipped_ids = {s.step_id for s in log.steps if s.status == "skipped"}
        from swarm.plan.dag import get_ready_steps

        ready = get_ready_steps(plan, completed_ids | skipped_ids)
        next_ready = [s.id for s in ready]
    except (json.JSONDecodeError, KeyError, PlanError, OSError):
        pass

    # Last completed step
    last_completed: str | None = None
    for outcome in reversed(log.steps):
        if outcome.status == "completed":
            last_completed = outcome.step_id
            break

    checkpoint_message: str | None = None
    if log.checkpoint_step_id:
        checkpoint_message = f"Paused at checkpoint: {log.checkpoint_step_id}"

    return json.dumps({
        "status": log.status,
        "progress": {
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        },
        "last_completed_step": last_completed,
        "next_ready_steps": next_ready,
        "checkpoint_message": checkpoint_message,
    })


@mcp.tool()
def plan_run_resume(
    run_log_path: str,
    plan_path: str = "",
    artifacts_dir: str = "",
    max_steps: str = "0",
) -> str:
    """Resume plan execution after a checkpoint or pause.

    Args:
        run_log_path: Path to the existing run log.
        plan_path: Path to the plan (empty = read from run log).
        artifacts_dir: Artifacts directory (empty = derive from run log
            path).
        max_steps: Max steps before next pause (default: ``"0"`` =
            unlimited).

    Returns:
        Same format as ``plan_run``.
    """
    log_p = Path(run_log_path)
    if not log_p.exists():
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    try:
        log = load_run_log(log_p)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        return json.dumps({"error": f"Failed to load run log: {exc}"})

    # Resolve plan path
    p_path_str = plan_path or log.plan_path
    if not p_path_str:
        return json.dumps({
            "error": "No plan_path provided and run log has no plan_path"
        })
    p_path = Path(p_path_str)

    if not p_path.exists():
        return json.dumps({"error": f"Plan file not found: {p_path_str}"})

    try:
        plan = load_plan(p_path)
    except (json.JSONDecodeError, KeyError, PlanError, OSError) as exc:
        return json.dumps({"error": f"Failed to load plan: {exc}"})

    # Idempotent: already completed
    if log.status == "completed":
        all_ids = {s.id for s in plan.steps}
        completed_ids = {s.step_id for s in log.steps if s.status == "completed"}
        return json.dumps({
            "status": "completed",
            "steps_executed": len(completed_ids),
            "steps_remaining": len(all_ids - completed_ids),
            "completed_step_ids": sorted(completed_ids),
            "failed_step_ids": [],
            "skipped_step_ids": [],
            "run_log_path": run_log_path,
            "checkpoint_message": None,
            "errors": [],
        })

    art_dir = (
        Path(artifacts_dir) if artifacts_dir else log_p.parent / "artifacts"
    )
    max_s = int(max_steps)

    try:
        run_state = init_run_state(plan, p_path, art_dir, log_p)
    except ExecutionError as exc:
        return json.dumps({"error": str(exc)})

    try:
        result = execute_plan(run_state, max_steps=max_s)
    except ExecutionError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps(result)


@mcp.tool()
def plan_run_cancel(run_log_path: str) -> str:
    """Cancel an active plan execution by marking the run log as cancelled.

    Note: this tool marks the run as cancelled in the log but does **not**
    terminate running subprocesses.  Background process handles live in the
    executor's ``RunState`` which is not accessible from a separate MCP
    tool invocation.  Process cleanup happens on the next resume attempt
    (the executor will see the ``cancelled`` status and skip further work).

    Args:
        run_log_path: Path to the run log.

    Returns:
        JSON ``{"ok": true, "killed_pids": [], "status": "cancelled"}``.
    """
    log_p = Path(run_log_path)
    if not log_p.exists():
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    try:
        log = load_run_log(log_p)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        return json.dumps({"error": f"Failed to load run log: {exc}"})

    log.status = "cancelled"
    log.finished_at = ""
    write_run_log(log, log_p)

    return json.dumps({
        "ok": True,
        "killed_pids": [],
        "status": "cancelled",
    })


@mcp.tool()
def plan_run_events(
    event_log_path: str = "",
    offset: str = "0",
) -> str:
    """Read real-time execution events from a plan run.

    Returns events since the given byte offset for efficient polling.
    Pass the returned offset in the next call to get only new events.

    Args:
        event_log_path: Path to the events.ndjson file.
        offset: Byte offset to read from (0 = beginning).

    Returns:
        JSON object: {"events": [...], "offset": N}.
    """
    from swarm.plan.events import EventLog

    path = Path(event_log_path)
    if not path.exists():
        return json.dumps({"events": [], "offset": 0})
    log = EventLog(path)
    events, new_offset = log.read_since(int(offset))
    return json.dumps({"events": events, "offset": new_offset})
