"""MCP tools for agent A/B experiments."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.experiments.api import ExperimentAPI
from swarm.mcp import state
from swarm.mcp.instance import mcp


def _get_experiment_api() -> ExperimentAPI:
    """Resolve the ExperimentAPI, creating it lazily from the plans directory."""
    if state.experiment_api is not None:
        return state.experiment_api
    plans_dir = Path(state.plans_dir) if state.plans_dir else Path.cwd()
    db_path = plans_dir / "experiments.db"
    return ExperimentAPI(db_path)


@mcp.tool()
def experiment_create(
    name: str,
    agent_a: str,
    agent_b: str,
    traffic_pct: str = "50.0",
    description: str = "",
) -> str:
    """Create a new A/B experiment comparing two agent variants.

    Once created, ``experiment_assign_variant`` routes traffic between
    the two variants using ``traffic_pct``.  Record outcomes via
    ``experiment_record_result`` and inspect aggregates with
    ``experiment_get_results``.

    Args:
        name: Unique experiment name.
        agent_a: Agent name/ID for variant A (control).
        agent_b: Agent name/ID for variant B (treatment).
        traffic_pct: Percentage of traffic routed to variant B
            (0-100). Default '50.0' = even split.
        description: Human-readable description.

    Returns:
        JSON object with the created experiment, or
        ``{"error": "..."}`` on validation failure.
    """
    if not name:
        return json.dumps({"error": "name is required"})
    if not agent_a:
        return json.dumps({"error": "agent_a is required"})
    if not agent_b:
        return json.dumps({"error": "agent_b is required"})
    try:
        pct = float(traffic_pct)
    except ValueError:
        return json.dumps({"error": f"Invalid traffic_pct: {traffic_pct!r}"})

    api = _get_experiment_api()
    try:
        result = api.create(
            name=name,
            agent_a=agent_a,
            agent_b=agent_b,
            traffic_pct=pct,
            description=description,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps(result)


@mcp.tool()
def experiment_list(status: str = "") -> str:
    """List experiments, optionally filtered by status.

    Args:
        status: Optional status filter ('active' or 'ended').
            Empty string returns all experiments.

    Returns:
        JSON array of experiment summary objects, newest first.
    """
    api = _get_experiment_api()
    try:
        experiments = api.list_experiments(status=status)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps(experiments)


@mcp.tool()
def experiment_get_results(experiment_name: str) -> str:
    """Get aggregated results for an experiment.

    Reports per-variant totals, success rate, average duration,
    token use, cost, and the current winner (if both variants have
    recorded data).

    Args:
        experiment_name: The experiment name.

    Returns:
        JSON object with per-variant aggregates and winner, or
        ``{"error": "..."}`` if not found.
    """
    if not experiment_name:
        return json.dumps({"error": "experiment_name is required"})

    api = _get_experiment_api()
    try:
        results = api.get_results(experiment_name)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps(results)


@mcp.tool()
def experiment_record_result(
    experiment_name: str,
    variant: str,
    success: str = "true",
    duration_secs: str = "0.0",
    tokens_used: str = "0",
    cost_usd: str = "0.0",
    run_id: str = "",
    step_id: str = "",
) -> str:
    """Record an outcome for an experiment variant.

    Args:
        experiment_name: The experiment name.
        variant: 'A' or 'B'.
        success: 'true' or 'false' (default 'true').
        duration_secs: Step duration in seconds (default '0.0').
        tokens_used: Tokens consumed (default '0').
        cost_usd: Cost in USD (default '0.0').
        run_id: Plan run identifier.
        step_id: Step identifier.

    Returns:
        JSON object with the recorded result, or
        ``{"error": "..."}`` on validation failure.
    """
    if not experiment_name:
        return json.dumps({"error": "experiment_name is required"})
    if variant not in ("A", "B"):
        return json.dumps({"error": f"variant must be 'A' or 'B', got {variant!r}"})

    success_bool = success.strip().lower() in ("true", "1", "yes")

    try:
        duration_val = float(duration_secs)
        tokens_val = int(tokens_used)
        cost_val = float(cost_usd)
    except ValueError as exc:
        return json.dumps({"error": f"Invalid numeric input: {exc}"})

    api = _get_experiment_api()
    try:
        result = api.record_result(
            experiment_name=experiment_name,
            variant=variant,
            success=success_bool,
            duration_secs=duration_val,
            tokens_used=tokens_val,
            cost_usd=cost_val,
            run_id=run_id,
            step_id=step_id,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps(result)


@mcp.tool()
def experiment_assign_variant(experiment_name: str) -> str:
    """Route a single invocation to variant A or B based on traffic split.

    Uses the experiment's ``traffic_pct`` to randomly select a variant.
    Call this at the start of each step that participates in the
    experiment, then record the outcome with
    ``experiment_record_result`` using the returned variant label.

    Args:
        experiment_name: The experiment name.

    Returns:
        JSON object ``{"agent": "...", "variant": "A"|"B"}``, or
        ``{"error": "..."}`` if the experiment is missing or ended.
    """
    if not experiment_name:
        return json.dumps({"error": "experiment_name is required"})

    api = _get_experiment_api()
    try:
        agent, variant = api.resolve_variant(experiment_name)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps({"agent": agent, "variant": variant})


@mcp.tool()
def experiment_end(experiment_name: str) -> str:
    """End an active experiment, freezing it from further routing.

    Recorded results are preserved.  Already-ended experiments
    return ``{"ok": false}``.

    Args:
        experiment_name: The experiment name.

    Returns:
        JSON object ``{"ok": true|false, "name": "..."}``.
    """
    if not experiment_name:
        return json.dumps({"error": "experiment_name is required"})

    api = _get_experiment_api()
    try:
        ended = api.end_experiment(experiment_name)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return json.dumps({"ok": ended, "name": experiment_name})
