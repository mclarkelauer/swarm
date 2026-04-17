"""Core execution loop for Swarm plans.

Implements the autonomous plan executor that drives a plan DAG to
completion by launching ``claude`` CLI subprocesses for each agent step.

"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from swarm.errors import ExecutionError
from swarm.memory.api import MemoryAPI
from swarm.memory.injection import format_memories_for_prompt
from swarm.plan.conditions import evaluate_condition
from swarm.plan.dag import get_ready_steps
from swarm.plan.events import EventLog, PlanEvent
from swarm.plan.interpolation import safe_interpolate
from swarm.plan.launcher import find_claude_binary, launch_agent, wait_with_timeout
from swarm.plan.models import Plan, PlanStep
from swarm.plan.pricing import estimate_cost_usd
from swarm.plan.run_log import (
    BackgroundStepRecord,
    RunLog,
    StepOutcome,
    load_run_log_resilient,
    write_run_log,
)

logger = structlog.get_logger()

_EXECUTOR_VERSION = "1.0.0"
_BACKGROUND_POLL_SECONDS = 1.0


# ---------------------------------------------------------------------------
# Helper: ISO timestamp
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# Helper: emit event
# ---------------------------------------------------------------------------

def _emit(run_state: RunState, event: PlanEvent) -> None:
    """Emit an event if event logging is enabled."""
    if run_state.event_log is not None:
        with contextlib.suppress(OSError):
            run_state.event_log.emit(event)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepExecution:
    """Record of a single execution attempt for a plan step."""

    step_id: str
    attempt: int  # 0-indexed; 0 = first try, 1 = first retry
    agent_type: str
    pid: int  # OS process ID of the claude subprocess
    started_at: str
    finished_at: str = ""
    exit_code: int | None = None
    output_artifact: str = ""
    is_critic: bool = False  # True when this is a critic review pass
    critic_iteration: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step_id": self.step_id,
            "attempt": self.attempt,
            "agent_type": self.agent_type,
            "pid": self.pid,
            "started_at": self.started_at,
        }
        if self.finished_at:
            d["finished_at"] = self.finished_at
        if self.exit_code is not None:
            d["exit_code"] = self.exit_code
        if self.output_artifact:
            d["output_artifact"] = self.output_artifact
        if self.is_critic:
            d["is_critic"] = True
            d["critic_iteration"] = self.critic_iteration
        if self.tokens_used > 0:
            d["tokens_used"] = self.tokens_used
        if self.cost_usd > 0.0:
            d["cost_usd"] = self.cost_usd
        if self.model:
            d["model"] = self.model
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepExecution:
        return cls(
            step_id=d["step_id"],
            attempt=d.get("attempt", 0),
            agent_type=d["agent_type"],
            pid=d.get("pid", -1),
            started_at=d["started_at"],
            finished_at=d.get("finished_at", ""),
            exit_code=d.get("exit_code"),
            output_artifact=d.get("output_artifact", ""),
            is_critic=d.get("is_critic", False),
            critic_iteration=d.get("critic_iteration", 0),
            tokens_used=d.get("tokens_used", 0),
            cost_usd=d.get("cost_usd", 0.0),
            model=d.get("model", ""),
        )


@dataclass(frozen=True)
class CriticResult:
    """Outcome of a critic review cycle."""

    approved: bool
    feedback: str = ""


@dataclass
class RunState:
    """Mutable runtime state for an active plan execution."""

    plan: Plan
    log: RunLog
    log_path: Path
    artifacts_dir: Path

    # Tracking
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    step_outcomes: dict[str, str] = field(default_factory=dict)

    # Background processes: step_id -> subprocess.Popen
    background_procs: dict[str, subprocess.Popen[str]] = field(default_factory=dict)

    # Retry tracking: step_id -> current attempt count
    retry_counts: dict[str, int] = field(default_factory=dict)

    # Retry delay tracking: step_id -> timestamp (time.monotonic()) after
    # which the step may be re-launched.  Avoids blocking the executor
    # with time.sleep() during retry backoff.
    retry_after: dict[str, float] = field(default_factory=dict)

    # Loop tracking: step_id -> current iteration count
    loop_iterations: dict[str, int] = field(default_factory=dict)

    # Critic tracking: step_id -> current critic iteration
    critic_iterations: dict[str, int] = field(default_factory=dict)

    # Replan tracking
    replan_count: int = 0

    # Decision overrides: step_id -> overridden condition value
    decision_overrides: dict[str, str] = field(default_factory=dict)

    # Optional memory API for automatic memory injection
    memory_api: MemoryAPI | None = None

    # Optional event log for real-time progress tracking
    event_log: EventLog | None = None

    # Maximum number of parallel foreground steps per wave (0 = serial)
    max_parallel: int = 0

    # Trace ID for distributed tracing — propagated to agent subprocesses
    trace_id: str = ""

    # Thread-safety lock for concurrent log writes during parallel execution
    _lock: threading.Lock = field(default_factory=threading.Lock)


# ---------------------------------------------------------------------------
# Helper: parse cost data from stderr
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """Read *path* as UTF-8, returning ``""`` on missing-or-unreadable."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_cost_fields(data: dict[str, Any], result: dict[str, Any]) -> bool:
    """Extract token/cost/model fields from a single CLI JSON object.

    Mutates *result* in place.  Returns ``True`` if any recognised cost
    field was extracted, ``False`` otherwise.  Supports both the
    ``--output-format json`` shape (``total_cost_usd`` + ``usage`` +
    ``modelUsage``) and the older streaming shape (``cost_usd`` + flat
    ``usage`` + ``model``).
    """
    matched = False

    usage = data.get("usage")
    if isinstance(usage, dict):
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        # Cache tokens are still billable input — fold them in so the
        # token total reflects what the API actually charged for.
        cache_create = int(usage.get("cache_creation_input_tokens", 0) or 0)
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        total = input_tokens + output_tokens + cache_create + cache_read
        if total > 0:
            result["tokens_used"] = total
            result["_input_tokens"] = input_tokens + cache_create + cache_read
            result["_output_tokens"] = output_tokens
            matched = True

    # Preferred current key, then legacy fallback.
    for key in ("total_cost_usd", "cost_usd"):
        if key in data:
            try:
                result["cost_usd"] = float(data[key])
                matched = True
                break
            except (TypeError, ValueError):
                continue

    # ``modelUsage`` is a {model_id: {...}} dict in the json output format.
    model_usage = data.get("modelUsage")
    if isinstance(model_usage, dict) and model_usage:
        # Pick the model that did the most work (largest reported cost,
        # falling back to first key).  This matches what humans expect to
        # see attributed to the step.
        best = max(
            model_usage.items(),
            key=lambda kv: float(kv[1].get("costUSD", 0.0)) if isinstance(kv[1], dict) else 0.0,
        )
        result["model"] = best[0]
        matched = True
    elif "model" in data and isinstance(data["model"], str):
        result["model"] = data["model"]
        matched = True

    return matched


def _parse_cost_data(artifacts_dir: Path, step_id: str) -> dict[str, Any]:
    """Parse token/cost/model usage from a completed step's CLI output.

    The ``claude`` CLI writes a single JSON result object to **stdout**
    when invoked with ``--output-format json``.  We parse that object for
    ``total_cost_usd``, ``usage`` token counts, and the active model.

    For backward compatibility with older CLI versions or
    ``--output-format stream-json``, we also fall back to scanning stderr
    line-by-line for any JSON object containing ``usage`` / ``cost_usd``.

    When token counts are present but no authoritative ``cost_usd``,
    :func:`swarm.plan.pricing.estimate_cost_usd` is used to produce a
    fallback estimate.

    If neither source yields any recognisable cost data, a
    ``cost_unparseable`` warning is logged so the silent-zero failure mode
    is at least visible in logs.

    Returns a dict with the optional keys ``tokens_used``, ``cost_usd``,
    ``model``, plus an internal ``cost_estimated`` flag when the cost was
    derived from the pricing table.  Internal helper keys
    (``_input_tokens`` / ``_output_tokens``) are stripped before return.
    """
    stdout_text = _read_text(artifacts_dir / f"{step_id}.stdout.log")
    stderr_text = _read_text(artifacts_dir / f"{step_id}.stderr.log")

    result: dict[str, Any] = {}
    matched_any = False

    # 1) Preferred source: the entire stdout is one JSON object when the
    #    CLI was invoked with --output-format json.
    stdout_stripped = stdout_text.strip()
    if stdout_stripped:
        try:
            top = json.loads(stdout_stripped)
        except json.JSONDecodeError:
            top = None
        if isinstance(top, dict):
            matched_any = _extract_cost_fields(top, result) or matched_any

    # 2) Fallback: scan every line of both streams for embedded JSON
    #    objects (handles --output-format stream-json and older builds
    #    that used to emit usage rows on stderr).
    for stream_text in (stdout_text, stderr_text):
        if not stream_text:
            continue
        for raw_line in stream_text.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                matched_any = _extract_cost_fields(data, result) or matched_any

    # 3) If we have tokens but the CLI did not give us a real dollar
    #    figure, estimate one from the pricing table.
    if "tokens_used" in result and "cost_usd" not in result:
        estimate = estimate_cost_usd(
            result.get("model", ""),
            int(result.get("_input_tokens", 0)),
            int(result.get("_output_tokens", 0)),
        )
        if estimate > 0.0:
            result["cost_usd"] = estimate
            result["cost_estimated"] = True

    # 4) If nothing recognisable came back from either stream, log a
    #    warning so the historic silent-zero failure is at least visible.
    if not matched_any and (stdout_text or stderr_text):
        logger.warning(
            "cost_unparseable",
            step_id=step_id,
            stdout_bytes=len(stdout_text),
            stderr_bytes=len(stderr_text),
        )

    # Strip internal helper keys before returning to callers.
    result.pop("_input_tokens", None)
    result.pop("_output_tokens", None)
    return result


# ---------------------------------------------------------------------------
# Helpers: find step, safe interpolation
# ---------------------------------------------------------------------------

def _find_step(plan: Plan, step_id: str) -> PlanStep:
    """Find a step in the plan by ID, raising ExecutionError if not found."""
    for s in plan.steps:
        if s.id == step_id:
            return s
    raise ExecutionError(f"Step '{step_id}' not found in plan")


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------

def record_success(
    run_state: RunState,
    step: PlanStep,
    attempt: int,
    message: str = "",
    started_at: str = "",
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    model: str = "",
) -> None:
    """Record a successful step execution."""
    now = _iso_now()
    outcome = StepOutcome(
        step_id=step.id,
        status="completed",
        started_at=started_at or now,
        finished_at=now,
        message=message,
        attempt=attempt,
        exit_code=0,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        model=model,
    )
    with run_state._lock:
        run_state.completed.add(step.id)
        run_state.step_outcomes[step.id] = "completed"
        run_state.log.steps.append(outcome)
        write_run_log(run_state.log, run_state.log_path)
    _emit(run_state, PlanEvent(
        event_type="step_completed",
        step_id=step.id,
        agent_type=step.agent_type,
    ))
    logger.info("step_completed", step_id=step.id, attempt=attempt, message=message)


def record_failure(
    run_state: RunState,
    step: PlanStep,
    attempt: int,
    message: str = "",
    exit_code: int | None = None,
    started_at: str = "",
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    model: str = "",
) -> None:
    """Record a failed step execution."""
    now = _iso_now()
    outcome = StepOutcome(
        step_id=step.id,
        status="failed",
        started_at=started_at or now,
        finished_at=now,
        message=message,
        attempt=attempt,
        exit_code=exit_code,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        model=model,
    )
    with run_state._lock:
        run_state.failed.add(step.id)
        run_state.step_outcomes[step.id] = "failed"
        run_state.log.steps.append(outcome)
        write_run_log(run_state.log, run_state.log_path)
    _emit(run_state, PlanEvent(
        event_type="step_failed",
        step_id=step.id,
        agent_type=step.agent_type,
        message=message,
    ))
    logger.warning("step_failed", step_id=step.id, attempt=attempt, message=message)


def record_skip(
    run_state: RunState,
    step: PlanStep,
    attempt: int,
    message: str = "",
    started_at: str = "",
) -> None:
    """Record a skipped step."""
    now = _iso_now()
    outcome = StepOutcome(
        step_id=step.id,
        status="skipped",
        started_at=started_at or now,
        finished_at=now,
        message=message,
        attempt=attempt,
    )
    with run_state._lock:
        run_state.skipped.add(step.id)
        run_state.step_outcomes[step.id] = "skipped"
        run_state.log.steps.append(outcome)
        write_run_log(run_state.log, run_state.log_path)
    _emit(run_state, PlanEvent(
        event_type="step_skipped",
        step_id=step.id,
    ))
    logger.info("step_skipped", step_id=step.id, attempt=attempt, message=message)


# ---------------------------------------------------------------------------
# Step execution: resolve payload
# ---------------------------------------------------------------------------

def _resolve_step_prompt(plan: Plan, step: PlanStep) -> str:
    """Interpolate the step prompt with plan variables."""
    return safe_interpolate(step.prompt, plan.variables)


def _build_agent_system_prompt(
    step: PlanStep,
    artifacts_dir: Path,
    memory_api: MemoryAPI | None = None,
) -> str:
    """Build the system prompt for an agent subprocess.

    Appends execution context (artifacts directory, output artifact path)
    to the agent's base prompt.  When *memory_api* is provided, recalled
    memories for the agent type are injected into the prompt.
    """
    parts: list[str] = []
    parts.append(f"You are executing step '{step.id}' of a Swarm plan.")
    if step.agent_type:
        parts.append(f"Agent type: {step.agent_type}")
    parts.append(f"Artifacts directory: {artifacts_dir}")
    if step.output_artifact:
        parts.append(
            f"Write your output to: {artifacts_dir / step.output_artifact}"
        )

    # Inject agent memories if available (best-effort — never block execution)
    if memory_api is not None and step.agent_type:
        try:
            memories = memory_api.recall(
                agent_name=step.agent_type,
                limit=10,
                min_relevance=0.2,
            )
            memory_block = format_memories_for_prompt(memories)
            if memory_block:
                parts.append("")
                parts.append(memory_block)
        except Exception:  # noqa: BLE001
            pass

    return "\n".join(parts)


def _trace_env(run_state: RunState, step: PlanStep) -> dict[str, str]:
    """Build trace environment variables for subprocess propagation."""
    env: dict[str, str] = {}
    if run_state.trace_id:
        env["SWARM_TRACE_ID"] = run_state.trace_id
        env["SWARM_SPAN_ID"] = f"{run_state.trace_id}:{step.id}"
    return env


# ---------------------------------------------------------------------------
# Foreground execution (section 5.2)
# ---------------------------------------------------------------------------

def execute_foreground(run_state: RunState, step: PlanStep) -> None:
    """Execute a foreground step, handling retries and critic loops."""
    _emit(run_state, PlanEvent(
        event_type="step_started",
        step_id=step.id,
        agent_type=step.agent_type,
    ))
    attempt = run_state.retry_counts.get(step.id, 0)
    retry_config = step.retry_config
    max_retries = retry_config.max_retries if retry_config else 0

    while True:
        step_started_at = _iso_now()
        prompt = _resolve_step_prompt(run_state.plan, step)
        system_prompt = _build_agent_system_prompt(step, run_state.artifacts_dir, memory_api=run_state.memory_api)
        tools = list(step.required_tools)

        proc = launch_agent(
            agent_prompt=system_prompt,
            step_prompt=prompt,
            tools=tools,
            artifacts_dir=run_state.artifacts_dir,
            step_id=step.id,
            env_extras=_trace_env(run_state, step),
        )

        exit_code = wait_with_timeout(proc, timeout=step.timeout if step.timeout > 0 else None)
        cost_data = _parse_cost_data(run_state.artifacts_dir, step.id)

        if exit_code == 0:
            # Check if critic loop is needed
            if step.critic_agent:
                critic_result = run_critic_loop(run_state, step)
                if not critic_result.approved:
                    if step.on_failure == "retry" and attempt < max_retries:
                        attempt += 1
                        run_state.retry_counts[step.id] = attempt
                        if retry_config:
                            delay = retry_config.delay_for_attempt(attempt)
                            time.sleep(delay)
                        continue
                    else:
                        record_failure(
                            run_state,
                            step,
                            attempt,
                            message=f"Critic rejected: {critic_result.feedback}",
                            exit_code=exit_code,
                            started_at=step_started_at,
                            tokens_used=cost_data.get("tokens_used", 0),
                            cost_usd=cost_data.get("cost_usd", 0.0),
                            model=cost_data.get("model", ""),
                        )
                        return

            record_success(
                run_state, step, attempt, started_at=step_started_at,
                tokens_used=cost_data.get("tokens_used", 0),
                cost_usd=cost_data.get("cost_usd", 0.0),
                model=cost_data.get("model", ""),
            )
            return

        # Handle failure
        if step.on_failure == "retry" and attempt < max_retries:
            logger.info(
                "step_retry",
                step_id=step.id,
                attempt=attempt,
                exit_code=exit_code,
            )
            attempt += 1
            run_state.retry_counts[step.id] = attempt
            if retry_config:
                delay = retry_config.delay_for_attempt(attempt)
                time.sleep(delay)
            continue
        elif step.on_failure == "skip":
            record_skip(
                run_state,
                step,
                attempt,
                message=f"Skipped after exit code {exit_code}",
                started_at=step_started_at,
            )
            return
        else:  # "stop"
            record_failure(
                run_state,
                step,
                attempt,
                message=f"Failed with exit code {exit_code}",
                exit_code=exit_code,
                started_at=step_started_at,
                tokens_used=cost_data.get("tokens_used", 0),
                cost_usd=cost_data.get("cost_usd", 0.0),
                model=cost_data.get("model", ""),
            )
            return


# ---------------------------------------------------------------------------
# Background execution (section 5.3)
# ---------------------------------------------------------------------------


def _record_background_start(
    run_state: RunState,
    step_id: str,
    pid: int,
    branch_index: int | None = None,
) -> None:
    """Persist a :class:`BackgroundStepRecord` to the run log.

    Called whenever a background subprocess (regular ``launch_background``
    task or a fan-out branch) is spawned.  On crash we walk the surviving
    records to either reattach polling or mark the step as failed.
    """
    record = BackgroundStepRecord(
        step_id=step_id,
        pid=pid,
        started_at=_iso_now(),
        branch_index=branch_index,
    )
    with run_state._lock:
        # Replace any prior in-flight record for the same step (covers
        # background retries that re-launch under the same id).
        run_state.log.background_steps = [
            b for b in run_state.log.background_steps if b.step_id != step_id
        ]
        run_state.log.background_steps.append(record)
        write_run_log(run_state.log, run_state.log_path)


def _record_background_finish(run_state: RunState, step_id: str) -> None:
    """Remove a :class:`BackgroundStepRecord` once the subprocess exits."""
    with run_state._lock:
        before = len(run_state.log.background_steps)
        run_state.log.background_steps = [
            b for b in run_state.log.background_steps if b.step_id != step_id
        ]
        if len(run_state.log.background_steps) != before:
            write_run_log(run_state.log, run_state.log_path)


def _pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* exists.

    Uses ``os.kill(pid, 0)`` which sends no signal but raises
    :class:`ProcessLookupError` if the PID is unknown and
    :class:`PermissionError` if it exists but we lack signal rights (still
    counts as alive for resume purposes).  Any other ``OSError`` is treated
    as "not alive" so we fall back to the safer mark-as-failed path.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def launch_background(run_state: RunState, step: PlanStep) -> None:
    """Launch a background step subprocess."""
    prompt = _resolve_step_prompt(run_state.plan, step)
    system_prompt = _build_agent_system_prompt(step, run_state.artifacts_dir, memory_api=run_state.memory_api)
    tools = list(step.required_tools)

    proc = launch_agent(
        agent_prompt=system_prompt,
        step_prompt=prompt,
        tools=tools,
        artifacts_dir=run_state.artifacts_dir,
        step_id=step.id,
    )

    run_state.background_procs[step.id] = proc
    _record_background_start(run_state, step.id, proc.pid)
    logger.info("background_launched", step_id=step.id, pid=proc.pid)


def reap_background(run_state: RunState) -> None:
    """Poll and collect finished background processes."""
    finished: list[tuple[str, int]] = []
    for step_id, proc in run_state.background_procs.items():
        exit_code = proc.poll()
        if exit_code is not None:
            finished.append((step_id, exit_code))

    for step_id, exit_code in finished:
        run_state.background_procs.pop(step_id)
        _record_background_finish(run_state, step_id)

        # Handle fan-out branch IDs (format: step_id::branch_index)
        if "::" in step_id:
            base_step_id = step_id.split("::")[0]
            # Check if all branches of this fan-out are done
            remaining = [
                k for k in run_state.background_procs
                if k.startswith(f"{base_step_id}::")
            ]
            if exit_code == 0:
                run_state.step_outcomes[step_id] = "completed"
                if not remaining:
                    # All branches done; mark the fan-out step itself
                    try:
                        fan_step = _find_step(run_state.plan, base_step_id)
                        all_branch_ids = [
                            f"{base_step_id}::{i}"
                            for i in range(
                                len(fan_step.fan_out_config.branches)
                                if fan_step.fan_out_config
                                else 0
                            )
                        ]
                        all_ok = all(
                            run_state.step_outcomes.get(bid) == "completed"
                            for bid in all_branch_ids
                        )
                        if all_ok:
                            record_success(run_state, fan_step, attempt=0)
                        else:
                            record_failure(
                                run_state,
                                fan_step,
                                attempt=0,
                                message="One or more fan-out branches failed",
                            )
                    except ExecutionError:
                        pass
            else:
                run_state.step_outcomes[step_id] = "failed"
                if not remaining:
                    try:
                        fan_step = _find_step(run_state.plan, base_step_id)
                        record_failure(
                            run_state,
                            fan_step,
                            attempt=0,
                            message="One or more fan-out branches failed",
                            exit_code=exit_code,
                        )
                    except ExecutionError:
                        pass
            continue

        # Regular background step
        step = _find_step(run_state.plan, step_id)
        if exit_code == 0:
            record_success(run_state, step, attempt=0)
        elif step.on_failure == "retry":
            attempt = run_state.retry_counts.get(step_id, 0)
            max_retries = (
                step.retry_config.max_retries if step.retry_config else 0
            )
            if attempt < max_retries:
                run_state.retry_counts[step_id] = attempt + 1
                if step.retry_config:
                    delay = step.retry_config.delay_for_attempt(attempt)
                    # Schedule re-launch after delay instead of blocking
                    run_state.retry_after[step_id] = time.monotonic() + delay
                else:
                    # No backoff configured; eligible immediately
                    run_state.retry_after[step_id] = time.monotonic()
            else:
                record_failure(
                    run_state,
                    step,
                    attempt,
                    message=f"Retries exhausted (exit code {exit_code})",
                    exit_code=exit_code,
                )
        elif step.on_failure == "skip":
            record_skip(
                run_state,
                step,
                attempt=0,
                message=f"Skipped after exit code {exit_code}",
            )
        else:
            record_failure(
                run_state,
                step,
                attempt=0,
                message=f"Failed with exit code {exit_code}",
                exit_code=exit_code,
            )


def _dispatch_deferred_retries(run_state: RunState) -> None:
    """Re-launch background steps whose retry delay has elapsed."""
    now = time.monotonic()
    ready_step_ids = [
        sid for sid, after in run_state.retry_after.items()
        if now >= after
    ]
    for step_id in ready_step_ids:
        run_state.retry_after.pop(step_id)
        step = _find_step(run_state.plan, step_id)
        launch_background(run_state, step)


# ---------------------------------------------------------------------------
# Loop execution (section 5.4)
# ---------------------------------------------------------------------------

def handle_loop(run_state: RunState, step: PlanStep) -> None:
    """Execute a loop step, iterating until condition is met or max reached."""
    config = step.loop_config
    if config is None:
        record_failure(
            run_state, step, attempt=0, message="Loop step missing loop_config"
        )
        return

    iteration = run_state.loop_iterations.get(step.id, 0)

    while iteration < config.max_iterations:
        # Evaluate termination condition
        if config.condition and evaluate_condition(
            config.condition,
            run_state.completed,
            step_outcomes=run_state.step_outcomes,
            artifacts_dir=run_state.artifacts_dir,
            iteration=iteration,
        ):
            record_success(
                run_state,
                step,
                attempt=0,
                message=f"Loop completed after {iteration} iterations",
            )
            return

        # Execute loop body
        prompt = _resolve_step_prompt(run_state.plan, step)
        system_prompt = _build_agent_system_prompt(step, run_state.artifacts_dir, memory_api=run_state.memory_api)
        tools = list(step.required_tools)

        proc = launch_agent(
            agent_prompt=system_prompt,
            step_prompt=prompt,
            tools=tools,
            artifacts_dir=run_state.artifacts_dir,
            step_id=f"{step.id}_iter{iteration}",
        )

        exit_code = wait_with_timeout(proc, timeout=step.timeout if step.timeout > 0 else None)

        if exit_code != 0:
            record_failure(
                run_state,
                step,
                attempt=0,
                message=f"Loop body failed at iteration {iteration}",
                exit_code=exit_code,
            )
            return

        iteration += 1
        run_state.loop_iterations[step.id] = iteration

    # Max iterations reached
    record_success(
        run_state,
        step,
        attempt=0,
        message=f"Loop hit max_iterations ({config.max_iterations})",
    )


# ---------------------------------------------------------------------------
# Checkpoint handling (section 5.6 -- design doc section 6.4)
# ---------------------------------------------------------------------------

def handle_checkpoint(run_state: RunState, step: PlanStep) -> None:
    """Handle a checkpoint step by pausing execution.

    Records the checkpoint in the run log so the executor can resume
    from this point.
    """
    message = ""
    if step.checkpoint_config:
        message = step.checkpoint_config.message
    if not message:
        message = step.prompt

    run_state.log.checkpoint_step_id = step.id
    run_state.log.status = "paused"
    write_run_log(run_state.log, run_state.log_path)

    _emit(run_state, PlanEvent(
        event_type="checkpoint_reached",
        step_id=step.id,
        message=message,
    ))
    logger.info("checkpoint_reached", step_id=step.id, message=message)


# ---------------------------------------------------------------------------
# Fan-out / Join (section 5.6)
# ---------------------------------------------------------------------------

def handle_fan_out(run_state: RunState, step: PlanStep) -> None:
    """Launch all fan-out branches as background processes."""
    if step.fan_out_config is None:
        record_failure(
            run_state,
            step,
            attempt=0,
            message="Fan-out step missing fan_out_config",
        )
        return

    for i, branch in enumerate(step.fan_out_config.branches):
        branch_id = f"{step.id}::{i}"
        branch_prompt = safe_interpolate(branch.prompt, run_state.plan.variables)
        system_prompt = _build_agent_system_prompt(step, run_state.artifacts_dir, memory_api=run_state.memory_api)
        tools = list(step.required_tools)

        proc = launch_agent(
            agent_prompt=system_prompt,
            step_prompt=branch_prompt,
            tools=tools,
            artifacts_dir=run_state.artifacts_dir,
            step_id=branch_id,
        )

        run_state.background_procs[branch_id] = proc
        _record_background_start(
            run_state, branch_id, proc.pid, branch_index=i,
        )
        logger.info(
            "fan_out_branch_launched",
            step_id=step.id,
            branch_index=i,
            agent_type=branch.agent_type,
            pid=proc.pid,
        )


def handle_join(run_state: RunState, step: PlanStep) -> None:
    """Execute a join step as a normal foreground task.

    The join step's agent collects output artifacts from its upstream
    dependencies (handled naturally by the DAG resolver).
    """
    execute_foreground(run_state, step)


# ---------------------------------------------------------------------------
# Subplan execution
# ---------------------------------------------------------------------------


def handle_subplan(run_state: RunState, step: PlanStep) -> None:
    """Execute a sub-plan as a nested plan execution."""
    if not step.subplan_path:
        record_failure(
            run_state, step, attempt=0,
            message="Subplan step missing subplan_path",
        )
        return

    subplan_path = Path(step.subplan_path)
    if not subplan_path.is_absolute():
        subplan_path = run_state.artifacts_dir / step.subplan_path

    if not subplan_path.exists():
        record_failure(
            run_state, step, attempt=0,
            message=f"Subplan file not found: {subplan_path}",
        )
        return

    try:
        from swarm.plan.parser import load_plan

        subplan = load_plan(subplan_path)
    except Exception as exc:
        record_failure(
            run_state, step, attempt=0,
            message=f"Failed to load subplan: {exc}",
        )
        return

    # Create sub-artifacts directory
    sub_artifacts = run_state.artifacts_dir / f"subplan_{step.id}"
    sub_log_path = sub_artifacts / "run_log.json"

    sub_state = init_run_state(
        subplan, subplan_path, sub_artifacts, sub_log_path,
    )
    # Inherit memory_api
    sub_state.memory_api = run_state.memory_api

    sub_result = execute_plan(sub_state)

    if sub_result["status"] == "completed":
        record_success(
            run_state, step, attempt=0,
            message=f"Subplan completed: {sub_result['steps_executed']} steps",
        )
    else:
        record_failure(
            run_state, step, attempt=0,
            message=f"Subplan {sub_result['status']}: {sub_result.get('failed_step_ids', [])}",
        )


# ---------------------------------------------------------------------------
# Decision step handling (dynamic replanning)
# ---------------------------------------------------------------------------


def handle_decision(run_state: RunState, step: PlanStep) -> None:
    """Evaluate decision conditions and activate/skip downstream steps."""
    if step.decision_config is None:
        record_failure(
            run_state,
            step,
            attempt=0,
            message="Decision step missing decision_config",
        )
        return

    activated: list[str] = []
    skipped: list[str] = []

    for action in step.decision_config.actions:
        if evaluate_condition(
            action.condition,
            run_state.completed,
            step_outcomes=run_state.step_outcomes,
            artifacts_dir=run_state.artifacts_dir,
        ):
            for activate_id in action.activate_steps:
                run_state.decision_overrides[activate_id] = ""
                activated.append(activate_id)
            for skip_id in action.skip_steps:
                skip_step = _find_step(run_state.plan, skip_id)
                record_skip(
                    run_state,
                    skip_step,
                    attempt=0,
                    message=f"Skipped by decision step '{step.id}'",
                )
                skipped.append(skip_id)

    record_success(
        run_state,
        step,
        attempt=0,
        message=f"Activated: {activated}, Skipped: {skipped}",
    )


# ---------------------------------------------------------------------------
# Critic loop (section 5.5)
# ---------------------------------------------------------------------------

def _read_verdict(artifacts_dir: Path, output_artifact: str) -> CriticResult:
    """Read the critic verdict file produced by the critic agent.

    The critic is expected to produce a file named
    ``<output_artifact>.verdict.json`` in the artifacts directory containing
    ``{"approved": true/false, "feedback": "..."}``.

    Returns ``CriticResult(approved=True)`` if the file is missing or
    malformed (fail-open).
    """
    verdict_path = artifacts_dir / f"{output_artifact}.verdict.json"
    if not verdict_path.exists():
        logger.warning("verdict_file_missing", path=str(verdict_path))
        return CriticResult(approved=True, feedback="No verdict file found (fail-open)")

    try:
        data = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("verdict_file_invalid", path=str(verdict_path), error=str(exc))
        return CriticResult(
            approved=True, feedback=f"Verdict file malformed (fail-open): {exc}"
        )

    return CriticResult(
        approved=bool(data.get("approved", True)),
        feedback=str(data.get("feedback", "")),
    )


def run_critic_loop(run_state: RunState, step: PlanStep) -> CriticResult:
    """Run the critic review loop per design section 5.5.

    Returns a :class:`CriticResult` indicating whether the output was
    approved.
    """
    max_iters = step.max_critic_iterations
    critic_iter = 0

    while critic_iter < max_iters:
        # Build critic prompt
        critic_prompt = (
            f"Review the output artifact '{step.output_artifact}' "
            f"at {run_state.artifacts_dir / step.output_artifact}.\n"
            f"Write your verdict to "
            f"{run_state.artifacts_dir / f'{step.output_artifact}.verdict.json'}\n"
            f'Use format: {{"approved": true/false, "feedback": "..."}}'
        )
        critic_system = (
            f"You are a critic reviewing the output of step '{step.id}'.\n"
            f"Agent type: {step.critic_agent}"
        )

        proc = launch_agent(
            agent_prompt=critic_system,
            step_prompt=critic_prompt,
            tools=list(step.required_tools),
            artifacts_dir=run_state.artifacts_dir,
            step_id=f"{step.id}_critic_{critic_iter}",
        )

        exit_code = wait_with_timeout(proc, timeout=step.timeout if step.timeout > 0 else None)

        if exit_code != 0:
            # Critic process failed -- fail-open
            logger.warning(
                "critic_process_failed",
                step_id=step.id,
                exit_code=exit_code,
            )
            return CriticResult(
                approved=True, feedback="Critic process failed (fail-open)"
            )

        # Read verdict
        verdict = _read_verdict(run_state.artifacts_dir, step.output_artifact)
        if verdict.approved:
            return verdict

        critic_iter += 1
        run_state.critic_iterations[step.id] = critic_iter

        if critic_iter < max_iters:
            # Re-run primary agent with critic feedback
            revised_prompt = _resolve_step_prompt(run_state.plan, step)
            revised_prompt += (
                f"\n\nCritic feedback (iteration {critic_iter}):\n"
                f"{verdict.feedback}"
            )
            system_prompt = _build_agent_system_prompt(step, run_state.artifacts_dir, memory_api=run_state.memory_api)

            proc = launch_agent(
                agent_prompt=system_prompt,
                step_prompt=revised_prompt,
                tools=list(step.required_tools),
                artifacts_dir=run_state.artifacts_dir,
                step_id=f"{step.id}_revision_{critic_iter}",
            )
            if wait_with_timeout(proc, timeout=step.timeout if step.timeout > 0 else None) != 0:
                return CriticResult(approved=False, feedback="Revision failed")

    return CriticResult(
        approved=False,
        feedback=f"Not approved after {max_iters} critic iterations",
    )


# ---------------------------------------------------------------------------
# Init / finalize
# ---------------------------------------------------------------------------

def _reconcile_orphan_backgrounds(rs: RunState) -> None:
    """Reattach or fail surviving background records on resume.

    For each :class:`BackgroundStepRecord` carried over from a prior
    crashed run we probe the PID with :func:`_pid_alive`:

    * **Live PID, ``on_failure == "skip"``** — kill the orphan and record
      a skip; the executor would skip on failure anyway.
    * **Live PID, ``on_failure == "retry"``** — kill the orphan and queue
      a retry on the next loop iteration so the executor re-launches it
      with a fresh subprocess we own.
    * **Live PID, otherwise** — mark the step as failed.  We can't recover
      the exit status of a process we didn't fork, so the safe action is
      a loud failure that surfaces the orphan to the operator.
    * **Dead PID** — also mark as failed (we missed the completion event
      so we have no way to know whether the work succeeded).

    Fan-out branch records (``base::index``) propagate failure up to the
    parent fan-out step.
    """
    surviving = list(rs.log.background_steps)
    if not surviving:
        return

    fan_out_failures: set[str] = set()

    for record in surviving:
        step_id = record.step_id
        is_branch = "::" in step_id
        base_id = step_id.split("::")[0] if is_branch else step_id

        try:
            step = _find_step(rs.plan, base_id)
        except ExecutionError:
            # Plan changed under us — drop the record and move on.
            continue

        alive = _pid_alive(record.pid)
        if alive:
            # Best-effort termination of the orphan so it stops chewing
            # tokens.  Failure to terminate is non-fatal — the worst case
            # is a leaked process, which is better than silently spawning
            # a duplicate or hanging on a PID we don't own.
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(record.pid, 15)  # SIGTERM
            logger.warning(
                "orphan_background_pid",
                step_id=step_id,
                pid=record.pid,
                action="terminated",
            )

        if is_branch:
            fan_out_failures.add(base_id)
            continue

        if alive and step.on_failure == "retry":
            attempt = rs.retry_counts.get(step_id, 0)
            rs.retry_counts[step_id] = attempt + 1
            rs.retry_after[step_id] = time.monotonic()
            logger.info(
                "orphan_background_retry_queued",
                step_id=step_id,
                attempt=attempt + 1,
            )
        elif step.on_failure == "skip":
            record_skip(
                rs,
                step,
                attempt=0,
                message=f"Orphan background PID {record.pid} from prior run",
            )
        else:
            record_failure(
                rs,
                step,
                attempt=0,
                message=(
                    f"Orphan background PID {record.pid} from prior run "
                    f"(alive={alive}); cannot recover exit status"
                ),
            )

    for base_id in fan_out_failures:
        try:
            fan_step = _find_step(rs.plan, base_id)
        except ExecutionError:
            continue
        if (
            base_id in rs.completed
            or base_id in rs.failed
            or base_id in rs.skipped
        ):
            continue
        record_failure(
            rs,
            fan_step,
            attempt=0,
            message="Orphan fan-out branches from prior run; cannot recover",
        )

    # All records have been reconciled — clear them.
    with rs._lock:
        rs.log.background_steps = []
        write_run_log(rs.log, rs.log_path)


def init_run_state(
    plan: Plan,
    plan_path: Path,
    artifacts_dir: Path,
    run_log_path: Path,
) -> RunState:
    """Initialize a RunState, loading existing run log if present for resume.

    Args:
        plan: The loaded execution plan.
        plan_path: Filesystem path to the plan JSON file.
        artifacts_dir: Directory for step artifacts.
        run_log_path: Path to the run log JSON file.

    Returns:
        A new or resumed :class:`RunState`.

    Raises:
        RunLogCorruptError: When the existing run log is corrupt and
            neither a ``.prev`` backup nor an ``events.ndjson`` file
            is available to reconstruct it.  Surfaces loudly rather than
            silently restarting (which would re-run completed steps).
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    backup_path = run_log_path.with_suffix(run_log_path.suffix + ".prev")
    events_path = artifacts_dir / "events.ndjson"
    have_state = (
        run_log_path.exists() or backup_path.exists() or events_path.exists()
    )

    log: RunLog | None = None
    if have_state:
        # load_run_log_resilient will:
        #   1) parse run_log_path
        #   2) fall back to <run_log_path>.prev
        #   3) reconstruct from events.ndjson
        #   4) raise RunLogCorruptError if all three fail
        # We deliberately let RunLogCorruptError propagate so the operator
        # is told loudly rather than silently restarting from scratch.
        log = load_run_log_resilient(run_log_path, events_path=events_path)
        # Backfill plan metadata if reconstruction left them empty.
        if not log.plan_path:
            log.plan_path = str(plan_path)
        if not log.plan_version:
            log.plan_version = plan.version

    if log is not None:
        rs = RunState(
            plan=plan,
            log=log,
            log_path=run_log_path,
            artifacts_dir=artifacts_dir,
        )
        # Reconstruct tracking from log
        for outcome in log.steps:
            if outcome.status == "completed":
                rs.completed.add(outcome.step_id)
                rs.step_outcomes[outcome.step_id] = "completed"
            elif outcome.status == "failed":
                rs.failed.add(outcome.step_id)
                rs.step_outcomes[outcome.step_id] = "failed"
            elif outcome.status == "skipped":
                rs.skipped.add(outcome.step_id)
                rs.step_outcomes[outcome.step_id] = "skipped"

        # Reconstruct replan_count from run log
        rs.replan_count = log.replan_count

        # If resuming from a checkpoint, mark the checkpoint step done
        if log.checkpoint_step_id:
            ckpt_id = log.checkpoint_step_id
            if ckpt_id not in rs.completed:
                rs.completed.add(ckpt_id)
                rs.step_outcomes[ckpt_id] = "completed"
                rs.log.steps.append(
                    StepOutcome(
                        step_id=ckpt_id,
                        status="completed",
                        started_at=_iso_now(),
                        finished_at=_iso_now(),
                        message="Checkpoint resumed",
                    )
                )
            log.checkpoint_step_id = ""

        log.status = "running"
        write_run_log(log, run_log_path)

        # Reconcile any background subprocesses that were in-flight when
        # the prior executor was killed — must run AFTER the log is in a
        # consistent "running" state.
        _reconcile_orphan_backgrounds(rs)
        return rs

    # Fresh run
    now = _iso_now()
    log = RunLog(
        plan_path=str(plan_path),
        plan_version=plan.version,
        started_at=now,
        status="running",
        executor_version=_EXECUTOR_VERSION,
    )
    write_run_log(log, run_log_path)

    import uuid as _uuid
    return RunState(
        plan=plan,
        log=log,
        log_path=run_log_path,
        artifacts_dir=artifacts_dir,
        trace_id=str(_uuid.uuid4()),
    )


def finalize(run_state: RunState, status: str) -> dict[str, Any]:
    """Finalize a run, write the final log, and return a summary dict."""
    _emit(run_state, PlanEvent(
        event_type="run_completed",
        message=status,
    ))
    run_state.log.status = status
    run_state.log.finished_at = _iso_now()

    # Record checkpoint message if paused at a checkpoint
    checkpoint_message: str | None = None
    if run_state.log.checkpoint_step_id:
        try:
            ckpt_step = _find_step(
                run_state.plan, run_state.log.checkpoint_step_id
            )
            if ckpt_step.checkpoint_config:
                checkpoint_message = ckpt_step.checkpoint_config.message
            if not checkpoint_message:
                checkpoint_message = ckpt_step.prompt
        except ExecutionError:
            checkpoint_message = None

    write_run_log(run_state.log, run_state.log_path)

    all_ids = {s.id for s in run_state.plan.steps}
    remaining = all_ids - run_state.completed - run_state.skipped - run_state.failed

    return {
        "status": status,
        "steps_executed": len(run_state.completed),
        "steps_remaining": len(remaining),
        "completed_step_ids": sorted(run_state.completed),
        "failed_step_ids": sorted(run_state.failed),
        "skipped_step_ids": sorted(run_state.skipped),
        "run_log_path": str(run_state.log_path),
        "checkpoint_message": checkpoint_message,
        "trace_id": run_state.trace_id,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Main loop (section 5.1)
# ---------------------------------------------------------------------------

def execute_plan(run_state: RunState, max_steps: int = 0) -> dict[str, Any]:
    """Main execution loop per design section 5.1.

    Drives the plan DAG to completion by dispatching steps to agent
    subprocesses.

    Args:
        run_state: The initialized :class:`RunState`.
        max_steps: Maximum number of steps to execute before pausing.
            ``0`` means unlimited.

    Returns:
        A summary dict with status, counts, and paths.
    """
    # Pre-flight: verify claude CLI is available
    find_claude_binary()

    _emit(run_state, PlanEvent(
        event_type="run_started",
        message=run_state.plan.goal,
    ))

    steps_executed = 0
    all_ids = {s.id for s in run_state.plan.steps}

    while True:
        # 1. Reap finished background processes and dispatch deferred retries
        reap_background(run_state)
        _dispatch_deferred_retries(run_state)

        # 2. Compute ready steps from the DAG
        done_or_skipped = run_state.completed | run_state.skipped
        ready = get_ready_steps(
            run_state.plan,
            done_or_skipped,
            artifacts_dir=run_state.artifacts_dir,
            step_outcomes=run_state.step_outcomes,
            decision_overrides=run_state.decision_overrides,
        )

        # 3. Filter out steps actively running in background, awaiting
        #    retry, or already failed
        ready = [
            s for s in ready
            if s.id not in run_state.background_procs
            and s.id not in run_state.retry_after
            and s.id not in run_state.failed
        ]

        # Whether there are in-flight or deferred-retry background tasks
        has_active_background = bool(
            run_state.background_procs or run_state.retry_after
        )

        # 4. Check termination conditions
        if not ready and not has_active_background:
            if (run_state.completed | run_state.skipped) >= all_ids:
                return finalize(run_state, "completed")
            if run_state.failed:
                return finalize(run_state, "failed")
            return finalize(run_state, "paused")

        # 5. If only background steps remain, wait for them
        if not ready and has_active_background:
            time.sleep(_BACKGROUND_POLL_SECONDS)
            continue

        # 6. Separate ready steps into foreground tasks eligible for
        #    parallel execution and steps that must run serially
        #    (checkpoints, loops, fan-outs, decisions, background tasks).
        parallel_fg: list[PlanStep] = []
        serial_steps: list[PlanStep] = []

        for step in ready:
            if step.type == "task" and step.spawn_mode == "foreground":
                parallel_fg.append(step)
            else:
                serial_steps.append(step)

        # 6a. Process serial steps first (checkpoints, loops, etc.)
        for step in serial_steps:
            if max_steps > 0 and steps_executed >= max_steps:
                return finalize(run_state, "paused")

            if step.type == "checkpoint":
                handle_checkpoint(run_state, step)
                return finalize(run_state, "paused")

            elif step.type == "loop":
                handle_loop(run_state, step)

            elif step.type == "fan_out":
                handle_fan_out(run_state, step)

            elif step.type == "join":
                handle_join(run_state, step)

            elif step.type == "decision":
                handle_decision(run_state, step)

            elif step.type == "subplan":
                handle_subplan(run_state, step)

            else:  # background task
                launch_background(run_state, step)

            steps_executed += 1

        # 6b. Execute foreground tasks — in parallel when max_parallel > 1
        #     and multiple steps are ready, otherwise serially.
        if parallel_fg:
            if max_steps > 0:
                remaining_budget = max_steps - steps_executed
                parallel_fg = parallel_fg[:remaining_budget]
                if not parallel_fg:
                    return finalize(run_state, "paused")

            use_parallel = (
                run_state.max_parallel > 1 and len(parallel_fg) > 1
            )

            if use_parallel:
                workers = min(run_state.max_parallel, len(parallel_fg))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(execute_foreground, run_state, step): step
                        for step in parallel_fg
                    }
                    for future in as_completed(futures):
                        future.result()  # propagate any exceptions
                        steps_executed += 1
            else:
                for step in parallel_fg:
                    execute_foreground(run_state, step)
                    steps_executed += 1
