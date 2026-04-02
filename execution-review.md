# Execution Loop (Stream A) -- Code Review

**Reviewer:** Architecture review
**Date:** 2026-04-01
**Verdict:** REQUEST CHANGES (2 blocking, 7 important, 9 suggestions)

---

## BLOCKING Issues

### B1. File handle leak in `launcher.py` -- stdout/stderr handles never closed

**File:** `src/swarm/plan/launcher.py`, lines 143-144, 153-171

`launch_agent()` opens two file handles (`stdout_fh`, `stderr_fh`) and passes them to `subprocess.Popen`. These handles are never closed -- not by the caller, not on process completion, not on any path. Over a plan with dozens of steps, this leaks file descriptors until the OS limit is hit.

The happy path leaks 2 FDs per step. The error path (line 161-168) correctly closes them on `OSError`, proving the author is aware of the issue but did not address the normal path.

```python
# Current: leaked on success path
stdout_fh = stdout_path.open("w")
stderr_fh = stderr_path.open("w")
# ...
proc = subprocess.Popen(cmd, stdout=stdout_fh, stderr=stderr_fh, ...)
# stdout_fh and stderr_fh are NEVER closed after this point
```

**Fix:** Either (a) close the FDs immediately after `Popen` (since `Popen` dups them), or (b) attach them to the `Popen` object or return them so the caller can close them after `wait()`. Option (a) is simplest and correct -- `Popen` inherits the FDs, so closing the Python file objects does not affect the subprocess.

---

### B2. Temp file leaked on every successful launch in `launcher.py`

**File:** `src/swarm/plan/launcher.py`, lines 113-118

`launch_agent()` creates a temp file via `tempfile.mkstemp()` on every call, writes the agent prompt to it, but never deletes it. The temp file is not even used -- the command passes `agent_prompt` as a CLI argument via `--system-prompt` (line 125-126) rather than reading from the file. So each agent launch leaks a temp file in `/tmp/`.

```python
fd, prompt_file_path = tempfile.mkstemp(suffix=".md", prefix=f"swarm_{step_id}_")
with open(fd, "w") as prompt_fh:
    prompt_fh.write(agent_prompt)
# prompt_file_path is NEVER used in the command, NEVER cleaned up
```

**Fix:** Either remove the temp file creation entirely (since the prompt is passed inline), or if the temp file is intended for debugging, register cleanup via `atexit` or delete after the process finishes.

---

## IMPORTANT Issues

### I1. `write_run_log` is not atomic -- partial writes corrupt resume

**File:** `src/swarm/plan/run_log.py`, line 99

```python
def write_run_log(log: RunLog, path: Path) -> None:
    path.write_text(json.dumps(log.to_dict(), indent=2) + "\n")
```

If the executor process is killed (SIGKILL, OOM, power failure) mid-write, the run log file will be partially written. On resume, `load_run_log` will fail with `JSONDecodeError`, which `init_run_state` handles by creating a fresh state -- discarding all progress.

The design doc (section 6.2) explicitly calls out crash recovery as a goal and says "Run log is persisted after every step outcome." This promise is undermined by non-atomic writes.

**Fix:** Write to a temp file in the same directory, then `os.replace()` (which is atomic on POSIX):

```python
def write_run_log(log: RunLog, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(log.to_dict(), indent=2) + "\n")
    os.replace(tmp, path)
```

---

### I2. `LoopConfig.max_iterations` default of 100,000 is dangerously high

**File:** `src/swarm/plan/models.py`, line 51

```python
max_iterations: int = 100_000
```

A loop step with no condition and the default `max_iterations` will launch 100,000 `claude` subprocesses. Each one is a full LLM session. This is clearly not the intent and would be catastrophically expensive. The design doc (section 5.4) lists this as a safety mechanism, but 100K is not a safety bound -- it is effectively unbounded.

**Fix:** Lower the default to something that actually provides safety, such as 10 or 50. Plan authors who genuinely need more can set it explicitly.

---

### I3. `reap_background` calls `time.sleep()` for retry delay -- blocks all execution

**File:** `src/swarm/plan/executor.py`, lines 437-439

When a background step fails and needs retry, `reap_background()` calls `time.sleep(delay)` inline. This blocks the entire single-threaded executor, preventing other background processes from being reaped and other ready steps from being dispatched.

```python
if step.retry_config:
    delay = step.retry_config.delay_for_attempt(attempt)
    time.sleep(delay)  # BLOCKS entire executor
launch_background(run_state, step)
```

This contradicts the design doc section 9 which states the executor is a poll-based event loop: "Simplicity. No thread-safety concerns for RunState mutations."

**Fix:** Track a `retry_after` timestamp per step and skip re-launch until the timestamp has passed, checking during each poll iteration.

---

### I4. `plan_run_cancel` does not actually kill background processes

**File:** `src/swarm/mcp/executor_tools.py`, lines 256-283

The design doc specifies `plan_run_cancel` should kill background processes and return their PIDs. The implementation only updates the run log status and always returns `killed_pids: []`:

```python
return json.dumps({
    "ok": True,
    "killed_pids": [],  # Always empty -- no processes are actually killed
    "status": "cancelled",
})
```

Since the cancel tool has no access to the `RunState` (which holds `background_procs`), it cannot kill anything. This makes `plan_run_cancel` purely cosmetic for in-progress runs.

**Fix:** Either (a) store PIDs in the run log so the cancel tool can signal them, or (b) maintain a module-level reference to the active `RunState` (as the design doc suggests with `state.executor`), or (c) document clearly that cancel only marks the log and does not terminate processes.

---

### I5. `record_success` uses the current time for both `started_at` and `finished_at`

**File:** `src/swarm/plan/executor.py`, lines 163-169

```python
def record_success(run_state, step, attempt, message=""):
    now = _iso_now()
    outcome = StepOutcome(
        step_id=step.id,
        started_at=now,   # Should be the ACTUAL start time
        finished_at=now,  # Same timestamp as started_at
        ...
    )
```

The same pattern applies to `record_failure` (line 189-198) and `record_skip` (line 215-224). The actual start time of the step is lost because `record_*` is called only at completion. The `started_at` field is always equal to `finished_at`, making duration analysis impossible.

**Fix:** Record the actual start time when the agent is launched (before `proc.wait()`), and pass it through to `record_*`.

---

### I6. `step_outcomes` is passed as `None` when it is actually an empty dict

**File:** `src/swarm/plan/executor.py`, lines 486-487 and 876-877

```python
step_outcomes=run_state.step_outcomes or None,
```

`run_state.step_outcomes` is initialized as `{}` (empty dict). Since `{}` is falsy in Python, `{} or None` evaluates to `None`. This means `step_failed:` conditions will never evaluate correctly when no steps have failed yet (because `evaluate_condition` skips the check when `step_outcomes is None`). While this is technically harmless for the `step_failed:` case (no outcomes means no failures), it is a latent bug -- if `step_outcomes` ever has entries and then gets accidentally reset to `{}`, conditions would silently break.

More importantly, it is confusing code. The intent is clearly "pass None when there are no outcomes" but the mechanism is fragile.

**Fix:** Pass `run_state.step_outcomes` directly (never None). The `evaluate_condition` function already handles an empty dict correctly.

---

### I7. Bare `except Exception` in MCP tools

**File:** `src/swarm/mcp/executor_tools.py`, lines 53-55, 149

```python
try:
    plan = load_plan(p_path)
except Exception as exc:
    return json.dumps({"error": f"Failed to load plan: {exc}"})
```

The project convention is to use custom exceptions (the `errors.py` hierarchy). Catching `Exception` masks unexpected bugs (e.g., `TypeError` from a code error in `load_plan`) by returning them as user-facing error messages. At minimum, catch `(json.JSONDecodeError, KeyError, PlanError)`.

---

## SUGGESTIONS

### S1. `execute_plan` passes `timeout=None` to `wait_with_timeout` everywhere

**Files:** `executor.py` lines 279, 511, 670, 707

The `agent_timeout` config field (default 300s) added to `SwarmConfig` is never used. Every call to `wait_with_timeout` passes `timeout=None`, meaning agents can run forever. The config field exists, the launcher accepts a `timeout` parameter, but the executor never threads them together.

**Fix:** Pass `config.agent_timeout` through `RunState` or as a parameter to `execute_plan`.

---

### S2. No `max_concurrent_background` enforcement

**File:** `src/swarm/config.py`, line 32

The `max_concurrent_background: int = 4` config field is defined but never referenced by the executor. The design doc section 9 states: "The `max_concurrent_background` config caps simultaneous subprocesses (default: 4). Additional background steps are queued." No queuing logic exists.

---

### S3. Fan-out step is never counted in `steps_executed`

**File:** `src/swarm/plan/executor.py`, line 924

After dispatching a fan-out step, `steps_executed += 1` runs, but the fan-out step is not marked as completed at that point (it completes asynchronously when all branches finish). This means `max_steps` accounting counts the dispatch but not the completion, which is inconsistent with foreground steps.

---

### S4. Plan version validation on resume is missing

**File:** `src/swarm/plan/executor.py`, `init_run_state` (lines 720-802)

The design doc section 10 states: "Verify plan version matches." The implementation loads the existing run log and reconstructs state but never checks `log.plan_version == plan.version`. If the plan was amended between runs, the executor will resume with potentially incompatible step definitions.

---

### S5. `_find_step` is O(n) per call -- used in hot loop

**File:** `src/swarm/plan/executor.py`, lines 137-142

`_find_step` does a linear scan of all plan steps. It is called in `reap_background` for every finished background process, and potentially multiple times per fan-out. For large plans this is quadratic. Consider building a `dict[str, PlanStep]` index at `RunState` init time.

---

### S6. Missing test: background step reaping and retry

The test suite has no tests for `reap_background()` or `launch_background()`. The fan-out code path in `reap_background` (the `"::" in step_id` branch) is also untested. These are complex code paths with error handling logic.

---

### S7. Missing test: `execute_plan` with loop steps

The `test_plan_loop_execution.py` file tests `handle_loop` in isolation but never tests a loop step going through the full `execute_plan` main loop. This means the `step.type == "loop"` dispatch in the main loop (line 910) is not integration-tested.

---

### S8. `plan_run_status` silently swallows exceptions from plan loading

**File:** `src/swarm/mcp/executor_tools.py`, lines 140-149

```python
try:
    plan = load_plan(Path(log.plan_path))
    ...
except Exception:
    pass  # Silently ignored
```

If the plan file is deleted or corrupted, the status tool returns `total: 0` and `next_ready_steps: []` with no indication that the plan could not be loaded.

---

### S9. Consider `from_dict` for `StepExecution` and `CriticResult`

`CriticResult` has no `to_dict`/`from_dict` methods, which is fine since it is ephemeral. But `StepExecution` has full serialization support yet is never actually persisted anywhere -- it is defined but unused. If it is for future use, note that in a comment; otherwise remove dead code.

---

## Coverage Gaps

| Code path | Test status |
|---|---|
| `reap_background()` -- regular step | NOT TESTED |
| `reap_background()` -- fan-out branch tracking | NOT TESTED |
| `launch_background()` | NOT TESTED |
| `handle_fan_out()` | NOT TESTED (no integration test through `execute_plan`) |
| `execute_plan` with `step.type == "loop"` | NOT TESTED (only `handle_loop` tested in isolation) |
| `execute_plan` with `step.type == "fan_out"` | NOT TESTED |
| `execute_plan` with `spawn_mode == "background"` | NOT TESTED |
| Background poll wait path (line 894-895) | NOT TESTED |
| `max_concurrent_background` throttling | NOT IMPLEMENTED, NOT TESTED |
| `agent_timeout` enforcement | NOT IMPLEMENTED, NOT TESTED |
| `plan_run_cancel` killing actual processes | NOT IMPLEMENTED, NOT TESTED |
| Plan version validation on resume | NOT IMPLEMENTED, NOT TESTED |
| `wait_with_timeout` with real timeout in executor | NOT TESTED (only tested in launcher unit tests) |
| `_safe_interpolate` with plan variables | NOT TESTED |
| `_build_agent_system_prompt` | NOT TESTED |
| File handle cleanup in `launch_agent` | NOT TESTED |
| Temp file cleanup in `launch_agent` | NOT TESTED |

Estimated coverage of new code: approximately 60-65%. The foreground execution path, retry logic, critic loop, loop handling, conditions, and MCP tool wrappers are well-tested. The background execution path and resource management are not tested at all.

---

## Positive Observations

1. **Frozen dataclasses used correctly.** `StepExecution`, `CriticResult`, `RetryConfig`, `StepOutcome` are all `frozen=True`. `RunState` is correctly mutable.

2. **Sparse serialization implemented correctly.** `RetryConfig.to_dict()` omits defaults. `StepOutcome.to_dict()` omits `attempt` when 0 and `exit_code` when None. `PlanStep.to_dict()` correctly handles the case where `retry_config` has all-default values (empty dict) by omitting the key entirely.

3. **Backward compatibility preserved.** `from_dict` methods use `.get()` with defaults for all new fields. Old run logs without `attempt`, `exit_code`, `executor_version`, or `checkpoint_step_id` will load correctly.

4. **MCP tool conventions followed.** String params in, `json.dumps()` out. Errors returned as `{"error": "..."}`.

5. **`from __future__ import annotations`** present in all new files.

6. **pathlib.Path used throughout.** No string path manipulation.

7. **Custom exceptions used.** `ExecutionError` follows the `SwarmError` hierarchy. No bare `except`.

8. **Fail-open critic verdict protocol is well-implemented.** Missing file, malformed JSON, and critic process failure all correctly fall through to approval.

9. **Design doc is thorough and the implementation follows it closely.** The pseudocode in sections 5.1-5.7 maps directly to the implementation.

10. **Test quality is high for covered paths.** The retry tests verify attempt counting, backoff delays, and exhaustion. The critic tests verify the full produce-review-revise cycle. The condition tests cover edge cases well.

---

## Summary

The implementation is well-structured and follows Swarm conventions closely. The foreground execution path, retry logic, critic loop, and checkpoint/resume protocol are solid. However, there are two blocking resource leaks in `launcher.py` (leaked file handles and temp files) that will cause problems in production use. The background execution path has several important issues (blocking sleep, no process cleanup, no concurrency limits) and is completely untested. The run log write is not crash-safe, which undermines the resume guarantee.

Fix the two blocking issues and the non-atomic write, then add tests for background execution before merging.
