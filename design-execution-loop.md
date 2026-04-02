# Execution Loop Subsystem -- Design Document

**Status:** Proposal
**Date:** 2026-04-01
**Author:** Architecture review
**Scope:** `src/swarm/plan/executor.py`, `src/swarm/mcp/executor_tools.py`, extensions to existing models

---

## 1. Problem Statement

Swarm has a complete planning system -- DAG construction, topological sort, condition gating, fan-out/join, templates, versioning -- but no execution runtime. The gap manifests in five concrete ways:

1. **Loop steps are inert.** `LoopConfig` has `condition` and `max_iterations` fields that are parsed and validated but never evaluated at runtime. A `loop` step is treated identically to a `task` step by the existing walker.

2. **Retry is a no-op.** `on_failure: "retry"` is accepted as valid by the parser but has no implementation. There is no retry count, no backoff, and no escalation path when retries are exhausted.

3. **Background spawning is cosmetic.** `spawn_mode: "background"` is a data field on `PlanStep` and is displayed in the dry-run table, but all steps execute sequentially in the interactive walker.

4. **Critic loops are metadata only.** `critic_agent` and `max_critic_iterations` are resolved into the `plan_execute_step` payload, but no produce-review-revise cycle exists.

5. **There is no autonomous executor.** The `swarm run` CLI is a manual step-by-step confirmation loop. There is no `plan_run` command or MCP tool that drives a plan to completion, spawning agents, collecting outputs, and advancing the DAG.

### Design principle: Swarm does not call LLMs

Swarm is LLM-agnostic. It prepares payloads and delegates execution to Claude Code sessions (via `os.execvp` or subprocess). The execution loop orchestrates *processes*, not *model calls*. Each agent invocation is a `claude` CLI subprocess with the agent's system prompt and tools attached via the MCP server.

---

## 2. Component Diagram

```
                         +---------------------+
                         |   CLI / MCP Client   |
                         |  (Claude session or  |
                         |   swarm run --auto)  |
                         +----------+----------+
                                    |
                      plan_run / plan_run_start
                                    |
                         +----------v----------+
                         |     Executor         |
                         |  (src/swarm/plan/    |
                         |   executor.py)       |
                         +--+------+------+----+
                            |      |      |
               +------------+      |      +-------------+
               |                   |                    |
    +----------v---+    +----------v------+   +---------v--------+
    | DAG Resolver  |    | Agent Launcher   |   | RunLog Writer    |
    | (dag.py)      |    | (launcher.py)    |   | (run_log.py)     |
    | get_ready     |    | spawn_agent()    |   | append_outcome() |
    | evaluate_cond |    | subprocess mgmt  |   | checkpoint_save  |
    +---------------+    +--------+---------+   +------------------+
                                  |
                    +-------------+-------------+
                    |             |             |
             +------v---+  +-----v-----+ +----v-------+
             | Foreground|  | Background| | Critic     |
             | (wait)    |  | (async)   | | Loop       |
             +-----------+  +-----------+ +------------+
                    |             |             |
                    v             v             v
            +-----------+  +-----------+  +-----------+
            | claude CLI |  | claude CLI |  | claude CLI |
            | subprocess |  | subprocess |  | subprocess |
            +-----------+  +-----------+  +-----------+
                    |             |             |
                    v             v             v
              +----------+  +----------+  +----------+
              | Artifacts |  | Artifacts |  | Artifacts |
              | (files)   |  | (files)   |  | (files)   |
              +----------+  +----------+  +----------+
                    |             |             |
                    +------+------+------+------+
                           |             |
                    +------v------+ +----v---------+
                    | artifacts.  | | run_log.json  |
                    | json (ndjson)| | (per-step)    |
                    +-------------+ +--------------+
```

### Integration points with existing subsystems

| Existing module | How the executor uses it |
|---|---|
| `plan/dag.py` | `get_ready_steps()` drives each tick of the main loop |
| `plan/conditions.py` | `evaluate_condition()` gates loop termination and step conditions |
| `plan/models.py` | `PlanStep`, `LoopConfig`, `FanOutConfig` define the step schema |
| `plan/run_log.py` | `RunLog`, `StepOutcome`, `append_step_outcome()` persist progress |
| `plan/parser.py` | `load_plan()`, `validate_plan()` for plan ingestion |
| `mcp/state.py` | `registry_api`, `forge_api`, `plans_dir` provide shared context |
| `mcp/plan_tools.py` | `plan_execute_step` resolves agent payloads (reused, not replaced) |
| `forge/frontmatter.py` | `render_frontmatter()` produces `.md` files for agent spawning |
| `registry/api.py` | `resolve_agent()` retrieves agent definitions for launcher |
| `config.py` | `SwarmConfig` provides `base_dir` and timeout settings |

---

## 3. Data Model Definitions

### 3.1 New: `RetryConfig` (frozen dataclass)

```python
# src/swarm/plan/models.py

@dataclass(frozen=True)
class RetryConfig:
    """Retry policy for a step with on_failure='retry'."""

    max_retries: int = 3
    backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.max_retries != 3:
            d["max_retries"] = self.max_retries
        if self.backoff_seconds != 2.0:
            d["backoff_seconds"] = self.backoff_seconds
        if self.backoff_multiplier != 2.0:
            d["backoff_multiplier"] = self.backoff_multiplier
        if self.max_backoff_seconds != 60.0:
            d["max_backoff_seconds"] = self.max_backoff_seconds
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RetryConfig:
        return cls(
            max_retries=d.get("max_retries", 3),
            backoff_seconds=d.get("backoff_seconds", 2.0),
            backoff_multiplier=d.get("backoff_multiplier", 2.0),
            max_backoff_seconds=d.get("max_backoff_seconds", 60.0),
        )

    def delay_for_attempt(self, attempt: int) -> float:
        """Return the delay in seconds before the given retry attempt (0-indexed)."""
        delay = self.backoff_seconds * (self.backoff_multiplier ** attempt)
        return min(delay, self.max_backoff_seconds)
```

### 3.2 Modified: `PlanStep` -- new field

Add `retry_config` to `PlanStep`:

```python
@dataclass(frozen=True)
class PlanStep:
    # ... existing fields ...
    retry_config: RetryConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        # ... existing logic ...
        if self.retry_config is not None:
            rc = self.retry_config.to_dict()
            if rc:  # sparse: only emit when non-default values exist
                d["retry_config"] = rc
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanStep:
        # ... existing logic ...
        retry_config = None
        if "retry_config" in d:
            retry_config = RetryConfig.from_dict(d["retry_config"])
        elif d.get("on_failure") == "retry":
            retry_config = RetryConfig()  # defaults
        return cls(..., retry_config=retry_config)
```

### 3.3 New: `StepExecution` (frozen dataclass)

Tracks a single execution attempt (there may be multiple per step due to retries or critic iterations).

```python
# src/swarm/plan/executor.py

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
        )
```

### 3.4 New: `RunState` (mutable, not frozen)

Extends `RunLog` with runtime bookkeeping that does not persist to the run log file. This is an in-memory structure only.

```python
# src/swarm/plan/executor.py

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

    # Loop tracking: step_id -> current iteration count
    loop_iterations: dict[str, int] = field(default_factory=dict)

    # Critic tracking: step_id -> current critic iteration
    critic_iterations: dict[str, int] = field(default_factory=dict)
```

### 3.5 Modified: `StepOutcome` -- new optional fields

```python
@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    status: str  # "completed", "failed", "skipped", "retrying"
    started_at: str
    finished_at: str
    message: str = ""
    attempt: int = 0
    exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
        }
        if self.attempt > 0:
            d["attempt"] = self.attempt
        if self.exit_code is not None:
            d["exit_code"] = self.exit_code
        return d
```

### 3.6 Modified: `RunLog` -- new optional fields

```python
@dataclass
class RunLog:
    plan_path: str
    plan_version: int
    started_at: str
    finished_at: str = ""
    status: str = "running"  # "running", "completed", "paused", "failed", "cancelled"
    steps: list[StepOutcome] = field(default_factory=list)
    # New: execution metadata
    executor_version: str = ""
    checkpoint_step_id: str = ""  # non-empty when paused at a checkpoint
```

---

## 4. New MCP Tool Specifications

### 4.1 `plan_run` -- start or resume autonomous execution

```
Name:        plan_run
Params:
  plan_path:      str   -- Path to the plan JSON file
  run_log_path:   str   -- Path for the run log (default: <plan_dir>/run_log.json)
  artifacts_dir:  str   -- Directory for step output artifacts (default: <plan_dir>/artifacts)
  max_steps:      str   -- Maximum steps to execute before pausing (default: "0" = unlimited)
  dry_run:        str   -- "true" to preview execution order without launching agents (default: "false")
  resume:         str   -- "true" to resume from existing run log (default: "true")

Return:
  JSON {
    "status": "completed" | "paused" | "failed" | "cancelled",
    "steps_executed": int,
    "steps_remaining": int,
    "completed_step_ids": [...],
    "failed_step_ids": [...],
    "run_log_path": str,
    "checkpoint_message": str | null,  // non-null when paused at checkpoint
    "errors": [...]
  }
```

**Behavior:** Loads the plan, initializes or resumes `RunState`, then enters the main execution loop (Section 5). Returns when the plan completes, a checkpoint is reached, `max_steps` is hit, or an unrecoverable failure occurs.

### 4.2 `plan_run_status` -- query a running or completed execution

```
Name:        plan_run_status
Params:
  run_log_path:  str  -- Path to the run log

Return:
  JSON {
    "status": str,
    "progress": {"completed": int, "failed": int, "skipped": int, "total": int},
    "active_background_steps": [...],  // step IDs of still-running background procs
    "last_completed_step": str | null,
    "next_ready_steps": [...],
    "checkpoint_message": str | null
  }
```

### 4.3 `plan_run_resume` -- resume after checkpoint or pause

```
Name:        plan_run_resume
Params:
  run_log_path:   str  -- Path to the existing run log
  plan_path:      str  -- Path to the plan (empty = read from run log)
  artifacts_dir:  str  -- Artifacts directory (empty = derive from run log path)
  max_steps:      str  -- Max steps before next pause (default: "0" = unlimited)

Return:
  Same as plan_run
```

### 4.4 `plan_run_cancel` -- cancel an active execution

```
Name:        plan_run_cancel
Params:
  run_log_path:  str  -- Path to the run log

Return:
  JSON {"ok": true, "killed_pids": [...], "status": "cancelled"}
```

---

## 5. Execution Algorithm

### 5.1 Main Loop (pseudocode)

```
function execute_plan(run_state: RunState, max_steps: int) -> str:
    steps_executed = 0
    plan = run_state.plan
    all_ids = {s.id for s in plan.steps}

    while True:
        # 1. Reap any finished background processes
        reap_background(run_state)

        # 2. Compute ready steps from the DAG
        ready = get_ready_steps(
            plan,
            run_state.completed | run_state.skipped,
            artifacts_dir=run_state.artifacts_dir,
            step_outcomes=run_state.step_outcomes,
        )

        # 3. Filter out steps that are actively running in background
        ready = [s for s in ready if s.id not in run_state.background_procs]

        # 4. Check termination conditions
        if not ready and not run_state.background_procs:
            if (run_state.completed | run_state.skipped) >= all_ids:
                return finalize(run_state, "completed")
            if run_state.failed:
                return finalize(run_state, "failed")
            return finalize(run_state, "paused")  # deadlock or unmet conditions

        # 5. If only background steps remain, wait for them
        if not ready and run_state.background_procs:
            wait_any_background(run_state, timeout=5.0)
            continue

        # 6. Process each ready step
        for step in ready:
            # 6a. Check max_steps limit
            if max_steps > 0 and steps_executed >= max_steps:
                return finalize(run_state, "paused")

            # 6b. Dispatch by step type
            match step.type:
                case "checkpoint":
                    handle_checkpoint(run_state, step)
                    return finalize(run_state, "paused")

                case "loop":
                    handle_loop(run_state, step)

                case "fan_out":
                    handle_fan_out(run_state, step)

                case "join":
                    handle_join(run_state, step)

                case "task":
                    if step.spawn_mode == "background":
                        launch_background(run_state, step)
                    else:
                        execute_foreground(run_state, step)

            steps_executed += 1
```

### 5.2 Foreground Step Execution

```
function execute_foreground(run_state: RunState, step: PlanStep):
    attempt = run_state.retry_counts.get(step.id, 0)
    max_retries = step.retry_config.max_retries if step.retry_config else 0

    while True:
        # 1. Resolve agent payload (reuses plan_execute_step logic)
        payload = resolve_step_payload(run_state.plan, step)

        # 2. Launch claude subprocess
        proc = launch_agent(payload, run_state.artifacts_dir)

        # 3. Wait for completion
        exit_code = proc.wait()

        # 4. Record execution
        now = iso_now()
        if exit_code == 0:
            # Check if critic loop is needed
            if step.critic_agent:
                critic_result = run_critic_loop(run_state, step)
                if not critic_result.approved:
                    # Critic rejected -- retry the step if allowed
                    if step.on_failure == "retry" and attempt < max_retries:
                        attempt += 1
                        run_state.retry_counts[step.id] = attempt
                        delay = step.retry_config.delay_for_attempt(attempt)
                        time.sleep(delay)
                        continue
                    else:
                        record_failure(run_state, step, attempt, "Critic rejected after max iterations")
                        return

            record_success(run_state, step, attempt)
            return

        # 5. Handle failure
        if step.on_failure == "retry" and attempt < max_retries:
            record_retry(run_state, step, attempt)
            attempt += 1
            run_state.retry_counts[step.id] = attempt
            delay = step.retry_config.delay_for_attempt(attempt)
            time.sleep(delay)
            continue
        elif step.on_failure == "skip":
            record_skip(run_state, step, attempt)
            return
        else:  # "stop"
            record_failure(run_state, step, attempt)
            return
```

### 5.3 Background Step Spawning and Reaping

```
function launch_background(run_state: RunState, step: PlanStep):
    payload = resolve_step_payload(run_state.plan, step)
    proc = launch_agent(payload, run_state.artifacts_dir, background=True)
    run_state.background_procs[step.id] = proc
    # Record started (but not finished)
    record_started(run_state, step)

function reap_background(run_state: RunState):
    finished = []
    for step_id, proc in run_state.background_procs.items():
        exit_code = proc.poll()
        if exit_code is not None:
            finished.append((step_id, exit_code))

    for step_id, exit_code in finished:
        proc = run_state.background_procs.pop(step_id)
        step = find_step(run_state.plan, step_id)

        if exit_code == 0:
            record_success(run_state, step, attempt=0)
        elif step.on_failure == "retry":
            attempt = run_state.retry_counts.get(step_id, 0)
            max_retries = step.retry_config.max_retries if step.retry_config else 0
            if attempt < max_retries:
                run_state.retry_counts[step_id] = attempt + 1
                delay = step.retry_config.delay_for_attempt(attempt)
                # Re-launch after delay (non-blocking)
                schedule_retry(run_state, step, delay)
            else:
                record_failure(run_state, step, attempt)
        elif step.on_failure == "skip":
            record_skip(run_state, step, attempt=0)
        else:
            record_failure(run_state, step, attempt=0)
```

### 5.4 Loop Execution

```
function handle_loop(run_state: RunState, step: PlanStep):
    config = step.loop_config
    iteration = run_state.loop_iterations.get(step.id, 0)

    while iteration < config.max_iterations:
        # 1. Evaluate termination condition
        if config.condition and evaluate_loop_condition(
            config.condition,
            run_state.completed,
            step_outcomes=run_state.step_outcomes,
            artifacts_dir=run_state.artifacts_dir,
            iteration=iteration,
        ):
            # Condition met -- loop is done
            record_success(run_state, step, attempt=0,
                           message=f"Loop completed after {iteration} iterations")
            return

        # 2. Execute the loop body (step prompt acts as the body)
        payload = resolve_step_payload(run_state.plan, step)
        proc = launch_agent(payload, run_state.artifacts_dir)
        exit_code = proc.wait()

        if exit_code != 0:
            record_failure(run_state, step, attempt=0,
                           message=f"Loop body failed at iteration {iteration}")
            return

        iteration += 1
        run_state.loop_iterations[step.id] = iteration

    # Max iterations reached
    record_success(run_state, step, attempt=0,
                   message=f"Loop hit max_iterations ({config.max_iterations})")
```

**Loop condition evaluation:** The existing `evaluate_condition()` function in `conditions.py` handles `artifact_exists:`, `step_completed:`, and `step_failed:` prefixes. For loop termination we reuse the same function but invert the semantics: the loop *continues* while the condition is False and *terminates* when it becomes True. This means a loop with `condition: "artifact_exists:report.md"` will keep iterating until `report.md` appears in the artifacts directory.

One new condition prefix is needed for loops:

```
iteration_ge:<N>    -- True when current iteration >= N
```

This is added to `conditions.py` with a new `iteration` parameter (default `None`, ignored when not in a loop context).

### 5.5 Critic Loop

```
function run_critic_loop(run_state: RunState, step: PlanStep) -> CriticResult:
    max_iters = step.max_critic_iterations
    critic_iter = 0

    while critic_iter < max_iters:
        # 1. Resolve the critic agent
        critic_payload = resolve_critic_payload(step)

        # 2. The critic reads the output artifact produced by the primary agent
        #    Its prompt instructs it to write a verdict file:
        #    <artifact>.verdict.json = {"approved": bool, "feedback": str}
        critic_payload.prompt = build_critic_prompt(
            step.output_artifact,
            run_state.artifacts_dir,
        )

        # 3. Launch critic subprocess
        proc = launch_agent(critic_payload, run_state.artifacts_dir)
        exit_code = proc.wait()

        if exit_code != 0:
            return CriticResult(approved=False, feedback="Critic process failed")

        # 4. Read verdict
        verdict = read_verdict(run_state.artifacts_dir, step.output_artifact)
        if verdict.approved:
            return CriticResult(approved=True, feedback=verdict.feedback)

        # 5. Not approved -- re-run the primary agent with feedback
        critic_iter += 1
        run_state.critic_iterations[step.id] = critic_iter

        if critic_iter < max_iters:
            # Re-run primary agent with critic feedback appended to prompt
            revised_payload = resolve_step_payload(run_state.plan, step)
            revised_payload.prompt += f"\n\nCritic feedback (iteration {critic_iter}):\n{verdict.feedback}"
            proc = launch_agent(revised_payload, run_state.artifacts_dir)
            if proc.wait() != 0:
                return CriticResult(approved=False, feedback="Revision failed")

    return CriticResult(approved=False, feedback=f"Not approved after {max_iters} critic iterations")
```

**Verdict protocol:** The critic agent is expected to produce a file `<output_artifact>.verdict.json` in the artifacts directory. The file contains `{"approved": true/false, "feedback": "..."}`. This is a file-based protocol, consistent with Swarm's artifact-centric design and avoiding any direct LLM API calls from Swarm.

### 5.6 Fan-out and Join

Fan-out steps launch all branches as concurrent background processes:

```
function handle_fan_out(run_state: RunState, step: PlanStep):
    for branch in step.fan_out_config.branches:
        payload = resolve_branch_payload(branch)
        proc = launch_agent(payload, run_state.artifacts_dir, background=True)
        branch_id = f"{step.id}::{branch.agent_type}"
        run_state.background_procs[branch_id] = proc

    # Don't mark the fan-out step as complete yet -- it completes when
    # all branches finish (tracked in reap_background via prefix matching)
```

Join steps simply wait for all their dependencies (which the DAG resolver already handles via `depends_on`). The join step itself runs as a normal task -- its agent collects the output artifacts from the upstream branches.

### 5.7 Agent Launcher

```python
# src/swarm/plan/launcher.py

def launch_agent(
    payload: AgentPayload,
    artifacts_dir: Path,
    background: bool = False,
    timeout: int | None = None,
) -> subprocess.Popen[str]:
    """Launch a claude CLI subprocess for an agent invocation.

    Writes the agent definition to a temporary .md file using
    render_frontmatter(), then invokes:

        claude --dangerously-skip-permissions \
               --system-prompt <prompt> \
               --output-dir <artifacts_dir> \
               --allowedTools <tools> \
               -p <interpolated_prompt>

    Returns the Popen handle. For foreground execution the caller
    calls proc.wait(). For background the handle is stored in RunState.
    """
```

Key implementation details:

- The agent's system prompt and tools come from the registry via `resolve_agent()`.
- The step prompt (interpolated with plan variables) is passed via `-p` (print mode) for non-interactive execution.
- `stdout` and `stderr` are captured to per-step log files: `<artifacts_dir>/<step_id>.stdout.log` and `<artifacts_dir>/<step_id>.stderr.log`.
- The agent is told (via system prompt appendix) to write its output artifact to `<artifacts_dir>/<output_artifact>` and to call `artifact_declare` via the MCP server.
- Environment variable `SWARM_STEP_ID` is set so the agent can identify itself.
- Environment variable `SWARM_ARTIFACTS_DIR` is set so the agent knows where to write.

---

## 6. Failure Modes and Error Handling

### 6.1 Step-level failures

| Scenario | `on_failure` | Behavior |
|---|---|---|
| Agent exits non-zero | `stop` | Step recorded as `failed`, execution halts, run status = `failed` |
| Agent exits non-zero | `retry` | Retry up to `max_retries` with exponential backoff; exhaustion -> record as `failed` + halt |
| Agent exits non-zero | `skip` | Step recorded as `skipped`, execution continues, downstream steps with `step_failed:` conditions can activate |
| Agent times out | any | Same as non-zero exit; timeout is treated as failure |
| Critic rejects output | `retry` | Re-run primary agent with feedback, up to `max_critic_iterations` |
| Critic rejects output | `stop` | Step recorded as `failed` |
| Critic process fails | any | Treated as if critic approved (fail-open) -- the primary output stands |
| Loop body fails | any | Loop terminates, step recorded as `failed` |
| Loop hits max_iterations | n/a | Step recorded as `completed` with message indicating max reached |

### 6.2 System-level failures

| Scenario | Behavior |
|---|---|
| Executor process crashes | Run log is persisted after every step outcome. Resume via `plan_run_resume` reads the log and recomputes `RunState`. Background processes become orphans (see 6.3). |
| Disk full | `write_run_log` raises `OSError`, executor catches and sets status to `failed`. |
| Plan file modified during run | Executor loads the plan once at start. Mid-run edits (via `plan_amend`) are not picked up until resume. This is intentional -- plan version is recorded in the run log and validated on resume. |
| Registry unavailable | Agent resolution fails, step is treated as failed with descriptive error. |
| `claude` CLI not found | Pre-flight check at executor start raises clear error before any steps run. |

### 6.3 Orphan process cleanup

Background processes that outlive the executor are tracked by PID in the run log. On resume, the executor checks each recorded PID:

- If the PID is still alive and matches the expected command signature, it re-attaches.
- If the PID is dead, the step is marked as `failed` (unless its output artifact exists, in which case it is marked `completed`).

PID reuse is mitigated by also recording the process start time. If the PID exists but the start time does not match, the process is considered an orphan.

### 6.4 Checkpoint handling

When the executor reaches a `checkpoint` step:
1. The run log is written with `status: "paused"` and `checkpoint_step_id` set.
2. The `plan_run` MCP tool returns with `status: "paused"` and `checkpoint_message` populated.
3. The orchestrating Claude session receives this return value and can present the checkpoint to the user.
4. The user instructs Claude to continue, which calls `plan_run_resume`.
5. On resume, the checkpoint step is marked as `completed` and execution continues.

---

## 7. Integration Points with Existing Code

### 7.1 Changes to existing files

| File | Change | Reason |
|---|---|---|
| `src/swarm/plan/models.py` | Add `RetryConfig` dataclass; add `retry_config` field to `PlanStep` | Retry policy configuration |
| `src/swarm/plan/run_log.py` | Add `attempt` and `exit_code` fields to `StepOutcome`; add `executor_version` and `checkpoint_step_id` to `RunLog` | Richer execution tracking |
| `src/swarm/plan/conditions.py` | Add `iteration_ge:` prefix support; add `iteration` param to `evaluate_condition` | Loop termination |
| `src/swarm/plan/parser.py` | Add `retry_config` to `from_dict`/validation; validate `retry_config` only when `on_failure == "retry"` | Plan validation |
| `src/swarm/mcp/state.py` | Add `executor: Executor | None = None` global | Expose executor state to MCP tools |
| `src/swarm/mcp/server.py` | Import `executor_tools` module for side-effect registration | Register new MCP tools |
| `src/swarm/errors.py` | Add `ExecutionError(SwarmError)` | Execution-specific errors |
| `src/swarm/config.py` | Add `agent_timeout: int = 300` and `max_concurrent_background: int = 4` to `SwarmConfig` | Executor configuration |

### 7.2 New files

| File | Purpose |
|---|---|
| `src/swarm/plan/executor.py` | Core execution loop, `RunState`, `StepExecution`, `CriticResult` |
| `src/swarm/plan/launcher.py` | Agent subprocess management -- spawn, wait, capture output |
| `src/swarm/mcp/executor_tools.py` | MCP tools: `plan_run`, `plan_run_status`, `plan_run_resume`, `plan_run_cancel` |
| `tests/plan/test_executor.py` | Unit tests for executor logic (mocked subprocesses) |
| `tests/plan/test_launcher.py` | Unit tests for agent launching |
| `tests/mcp/test_executor_tools.py` | Integration tests for executor MCP tools |

### 7.3 Unchanged modules

The following modules are used as-is, with no modifications:

- `plan/dag.py` -- `get_ready_steps()` and `topological_sort()` are the DAG engine
- `plan/templates.py` -- Template system is orthogonal to execution
- `plan/versioning.py` -- Version management is orthogonal
- `plan/discovery.py` -- Plan directory discovery is reused
- `forge/api.py` -- Agent CRUD is unchanged
- `forge/frontmatter.py` -- Renders agent `.md` files for the launcher
- `registry/api.py` -- Agent resolution is used by the launcher
- `mcp/artifact_tools.py` -- Agents call these during execution; executor does not
- `mcp/forge_tools.py` -- Orthogonal
- `mcp/discovery_tools.py` -- Orthogonal
- `cli/run_cmd.py` -- The interactive walker remains as a lightweight alternative

---

## 8. CLI Integration

A new `--auto` flag on the existing `swarm run` command, plus new subcommands:

```
swarm run --auto [--max-steps N] [PATH | --latest]
    Autonomous execution. Launches agents, collects outputs, advances DAG.
    Pauses at checkpoints and returns control to the user.

swarm run resume [--max-steps N] [--log-file PATH]
    Resume after a checkpoint or pause.

swarm run cancel [--log-file PATH]
    Cancel an active execution and kill background processes.
```

The existing interactive mode (`swarm run` without `--auto`) is preserved unchanged.

---

## 9. Concurrency Model

The executor runs in a single thread with a poll-based event loop. This is deliberate:

1. **Simplicity.** No thread-safety concerns for `RunState` mutations.
2. **subprocess.Popen is non-blocking.** `proc.poll()` checks completion without blocking.
3. **Limited parallelism.** The `max_concurrent_background` config caps simultaneous subprocesses (default: 4). Additional background steps are queued.
4. **Foreground steps serialize.** Within a single wave, foreground steps run one at a time. Background steps within the same wave run concurrently.
5. **Wave advancement.** The main loop re-evaluates `get_ready_steps()` after every step completion. This naturally handles wave boundaries -- the next wave's steps become ready when the previous wave's outputs satisfy their dependencies.

The poll interval is 1 second when background processes are active. The executor calls `reap_background()` at the top of each iteration.

---

## 10. Checkpoint and Resume Protocol

Checkpoints create a clean pause boundary:

1. **On checkpoint:** Write run log with `status: "paused"`, `checkpoint_step_id: step.id`, `checkpoint_config.message` as the reason. Kill no processes (background steps continue -- they were launched before the checkpoint).
2. **On resume:** Load run log, reconstruct `RunState` from completed/failed/skipped step IDs. Verify plan version matches. Mark the checkpoint step as `completed`. Re-enter the main loop.
3. **Idempotent resume:** Calling resume on an already-completed run is a no-op that returns `status: "completed"`.

---

## 11. Run Log Evolution

The run log schema gains two new top-level fields (`executor_version`, `checkpoint_step_id`) and two new per-step fields (`attempt`, `exit_code`). Both additions are backward compatible:

- Existing run logs (from the interactive walker) have no `attempt` or `exit_code` fields. The executor reads these as defaults (0 and None respectively).
- `executor_version` defaults to `""`, which means "interactive walker" (legacy).
- The `write_run_log` / `load_run_log` functions use the existing `from_dict` pattern, which silently ignores unknown keys and applies defaults for missing keys.
- No database migration is needed -- run logs are JSON files, not SQLite.

---

## 12. Open Risks

### R1: Subprocess reliability
**Risk:** Long-running claude subprocesses may hang, consume excessive resources, or produce partial output.
**Mitigation:** Per-step timeout (`agent_timeout` in config). The launcher sends `SIGTERM`, waits 10 seconds, then `SIGKILL`. Partial output artifacts are detected by checking file size against a minimum threshold.

### R2: Verdict file protocol
**Risk:** The critic agent may not produce the expected `<artifact>.verdict.json` file, or may produce malformed JSON.
**Mitigation:** If the verdict file is missing or malformed after critic completion, the executor treats it as "approved" (fail-open). This prevents critic failures from blocking the entire plan. A warning is logged.

### R3: PID-based process tracking
**Risk:** PID reuse by the OS could cause the executor to re-attach to the wrong process on resume.
**Mitigation:** Record `(pid, started_at)` tuples. On resume, verify the process start time matches. Use `/proc/<pid>/stat` on Linux or `ps -p <pid> -o lstart=` on macOS. If validation fails, treat the step as an orphan failure.

### R4: Disk space exhaustion
**Risk:** Per-step stdout/stderr logs and output artifacts could consume significant disk space during large plan executions.
**Mitigation:** Log rotation is out of scope for v1. The `plan_retrospective` tool already flags unused artifacts. A future enhancement could add a `plan_clean` tool.

### R5: Claude CLI availability and version
**Risk:** The executor depends on the `claude` CLI being installed and supporting the `-p` (print mode) flag for non-interactive execution.
**Mitigation:** Pre-flight check at executor start validates the claude binary exists and supports the required flags. Clear error message with install instructions on failure.

### R6: Concurrent plan modifications
**Risk:** A user could call `plan_amend` or `plan_patch_step` while the executor is running, creating a plan version mismatch.
**Mitigation:** The executor loads the plan once and records the version in the run log. On resume, it validates the version matches. If a new version exists, resume requires explicit `--plan-path` pointing to the new version, which is a conscious decision.

### R7: MCP server lifecycle
**Risk:** The executor MCP tools (`plan_run`) may be long-running, potentially exceeding MCP tool timeout expectations.
**Mitigation:** The `plan_run` MCP tool supports `max_steps` for bounded execution. For truly autonomous runs, the CLI `swarm run --auto` is the preferred interface (no MCP timeout constraints). The MCP tool is designed for incremental use: call `plan_run` with `max_steps=5`, inspect results, call `plan_run_resume` for the next batch.

### R8: Fan-out branch identity
**Risk:** Fan-out branches need unique identifiers for tracking in the run log, but they are not first-class `PlanStep` objects with their own `id` fields.
**Mitigation:** Use synthetic IDs of the form `<step_id>::<branch_index>` (e.g., `fan-out-1::0`, `fan-out-1::1`). These are used only in `RunState.background_procs` and execution logs, never in the plan DAG itself. The fan-out step's own ID is marked completed only when all branches finish.

---

## 13. Testing Strategy

### Unit tests (mocked subprocesses)

- **Executor loop:** Test that `get_ready_steps` is called correctly, steps are dispatched by type, and the loop terminates on all plan states (complete, failed, paused).
- **Retry logic:** Test exponential backoff calculation, max_retries exhaustion, escalation to failure/skip.
- **Loop execution:** Test condition evaluation per iteration, max_iterations enforcement, loop body failure.
- **Critic loop:** Test verdict file parsing, re-run with feedback, max_critic_iterations.
- **Background reaping:** Test poll-based completion detection, orphan handling.
- **Resume:** Test RunState reconstruction from run log, checkpoint advancement.

### Integration tests (real subprocess, mocked claude)

- Create a mock `claude` script that writes a predetermined output artifact and exits with a configurable code.
- Run the executor against a small plan (3-5 steps) with the mock claude.
- Verify run log contents, artifact files, and step ordering.

All tests use `tmp_path` fixtures for filesystem isolation, consistent with the existing test conventions.

---

## 14. Implementation Order

1. **Phase 1: Foundation** -- `RetryConfig`, `StepOutcome` extensions, `RunLog` extensions, `launcher.py` with subprocess management. Tests for all new models.

2. **Phase 2: Core loop** -- `executor.py` with foreground-only execution. No background, no loops, no critics. `plan_run` MCP tool for basic sequential execution. End-to-end test with mock claude.

3. **Phase 3: Retry** -- `on_failure: "retry"` implementation with backoff. Tests for retry exhaustion and escalation.

4. **Phase 4: Background** -- `spawn_mode: "background"` with poll-based reaping. `max_concurrent_background` throttling. Tests for concurrent step execution.

5. **Phase 5: Loops** -- `LoopConfig` evaluation, `iteration_ge:` condition, loop body execution. Tests for termination conditions.

6. **Phase 6: Critic loops** -- Verdict file protocol, produce-review-revise cycle. Tests with mock critic agent.

7. **Phase 7: CLI and polish** -- `swarm run --auto`, `swarm run resume`, `swarm run cancel`. Resume from checkpoint. Documentation updates.
