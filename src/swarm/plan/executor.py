"""Core execution loop for Swarm plans.

Implements the autonomous plan executor that drives a plan DAG to
completion by launching ``claude`` CLI subprocesses for each agent step.

"""

from __future__ import annotations

import contextlib
import json
import re
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
from swarm.plan.launcher import find_claude_binary, launch_agent, wait_with_timeout
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, StepOutcome, load_run_log, write_run_log

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

    # Thread-safety lock for concurrent log writes during parallel execution
    _lock: threading.Lock = field(default_factory=threading.Lock)


# ---------------------------------------------------------------------------
# Helper: parse cost data from stderr
# ---------------------------------------------------------------------------


def _parse_cost_data(artifacts_dir: Path, step_id: str) -> dict[str, Any]:
    """Parse token usage from claude CLI stderr output.

    The claude CLI outputs usage data to stderr.  We look for JSON-formatted
    usage data or known patterns.

    Returns dict with tokens_used, cost_usd, model (all optional).
    """
    stderr_path = artifacts_dir / f"{step_id}.stderr.log"
    if not stderr_path.exists():
        return {}

    try:
        content = stderr_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    result: dict[str, Any] = {}

    # Try to find JSON usage data in stderr
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if "usage" in data:
                usage = data["usage"]
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                result["tokens_used"] = input_tokens + output_tokens
            if "model" in data:
                result["model"] = data["model"]
            if "cost_usd" in data:
                result["cost_usd"] = float(data["cost_usd"])
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

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


def _safe_interpolate(template: str, variables: dict[str, str]) -> str:
    """Interpolate ``{key}`` placeholders, leaving unknown keys intact."""
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))
    return re.sub(r"\{(\w+)\}", _replacer, template)


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
    return _safe_interpolate(step.prompt, plan.variables)


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
        branch_prompt = _safe_interpolate(branch.prompt, run_state.plan.variables)
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
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Attempt to load existing run log for resume
    if run_log_path.exists():
        try:
            log = load_run_log(run_log_path)
        except (json.JSONDecodeError, KeyError):
            log = None

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

    return RunState(
        plan=plan,
        log=log,
        log_path=run_log_path,
        artifacts_dir=artifacts_dir,
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
