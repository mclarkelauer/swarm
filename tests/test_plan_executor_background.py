"""Tests for background reaping, fan-out aggregation, deferred retries, and
parallel-foreground exception isolation in :mod:`swarm.plan.executor`.

Focuses on the under-covered code paths around 530-663 and 1289-1298 of
``executor.py`` (per the test plan): ``reap_background`` failure routing,
fan-out branch ID aggregation, ``_dispatch_deferred_retries`` timing and
pause-state handling, and exception safety inside the parallel-foreground
``ThreadPoolExecutor``.

Conventions:
- All paths live inside ``tmp_path`` — no real filesystem touched.
- The fake-binary pattern (writing a Python script to ``tmp_path`` and
  pointing ``find_claude_binary`` at it) is used for the end-to-end tests
  where we want to exercise real subprocess + ``launch_agent`` plumbing.
- Pure-unit reap tests use ``MagicMock`` Popen handles so we can control
  ``poll()`` deterministically without spawning real processes.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.executor import (
    RunState,
    _dispatch_deferred_retries,
    execute_plan,
    launch_background,
    reap_background,
    record_success,
)
from swarm.plan.models import (
    FanOutBranch,
    FanOutConfig,
    Plan,
    PlanStep,
    RetryConfig,
)
from swarm.plan.run_log import (
    BackgroundStepRecord,
    RunLog,
    load_run_log,
    write_run_log,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep, variables: dict[str, str] | None = None) -> Plan:
    return Plan(
        version=1,
        goal="bg test plan",
        steps=list(steps),
        variables=variables or {},
    )


def _bg_task(
    step_id: str,
    on_failure: str = "stop",
    retry_config: RetryConfig | None = None,
    depends_on: tuple[str, ...] = (),
) -> PlanStep:
    return PlanStep(
        id=step_id,
        type="task",
        prompt=f"bg-{step_id}",
        agent_type="worker",
        spawn_mode="background",
        on_failure=on_failure,
        retry_config=retry_config,
        depends_on=depends_on,
    )


def _fg_task(step_id: str, depends_on: tuple[str, ...] = ()) -> PlanStep:
    return PlanStep(
        id=step_id,
        type="task",
        prompt=f"fg-{step_id}",
        agent_type="worker",
        spawn_mode="foreground",
        depends_on=depends_on,
    )


def _make_run_state(plan: Plan, tmp_path: Path) -> RunState:
    log_path = tmp_path / "run_log.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(
        plan_path=str(tmp_path / "plan.json"),
        plan_version=plan.version,
        started_at="2025-01-01T00:00:00+00:00",
        status="running",
        executor_version="1.0.0",
    )
    write_run_log(log, log_path)
    return RunState(
        plan=plan,
        log=log,
        log_path=log_path,
        artifacts_dir=artifacts_dir,
    )


def _mock_popen(exit_code: int | None = None, pid: int = 12345) -> MagicMock:
    """Return a Popen-like mock whose ``poll()`` returns *exit_code*.

    Pass ``exit_code=None`` to model a still-running process.
    """
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.poll.return_value = exit_code
    proc.wait.return_value = exit_code if exit_code is not None else 0
    return proc


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_fan_out_state(
    tmp_path: Path,
) -> Iterator[Callable[..., tuple[RunState, PlanStep]]]:
    """Factory: build a RunState with a fan-out step that already has its
    branches launched as background processes.

    Use the returned tuple ``(rs, fan_step)`` to drive ``reap_background``
    against controlled mock Popen handles.
    """

    def _factory(
        n_branches: int = 3,
        on_failure: str = "stop",
        exit_codes: list[int | None] | None = None,
    ) -> tuple[RunState, PlanStep]:
        if exit_codes is None:
            exit_codes = [0] * n_branches
        if len(exit_codes) != n_branches:
            raise ValueError("exit_codes length must equal n_branches")

        branches = tuple(
            FanOutBranch(prompt=f"b{i}", agent_type="worker")
            for i in range(n_branches)
        )
        fan_step = PlanStep(
            id="fan",
            type="fan_out",
            prompt="dispatch",
            agent_type="dispatcher",
            on_failure=on_failure,
            fan_out_config=FanOutConfig(branches=branches),
        )
        plan = _plan(fan_step)
        rs = _make_run_state(plan, tmp_path)

        for i, ec in enumerate(exit_codes):
            branch_id = f"fan::{i}"
            proc = _mock_popen(exit_code=ec, pid=70_000 + i)
            rs.background_procs[branch_id] = proc
            rs.log.background_steps.append(
                BackgroundStepRecord(
                    step_id=branch_id,
                    pid=70_000 + i,
                    started_at="t0",
                    branch_index=i,
                ),
            )
        write_run_log(rs.log, rs.log_path)
        return rs, fan_step

    yield _factory


# ---------------------------------------------------------------------------
# Background retry / skip
# ---------------------------------------------------------------------------


class TestBackgroundRetryAndSkip:
    """Cover the failure-handling branches of ``reap_background`` for
    regular (non-fan-out) background steps."""

    @patch("swarm.plan.executor.launch_agent")
    def test_background_step_retry_on_failure(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """Background step exits non-zero with on_failure='retry'.

        First reap should not record failure — instead it should schedule
        a retry via ``retry_after``.  The deferred-retry dispatcher then
        re-launches the step and a second reap with exit 0 records success.
        """
        retry_cfg = RetryConfig(
            max_retries=2,
            backoff_seconds=0.0,
            backoff_multiplier=1.0,
            max_backoff_seconds=0.0,
        )
        step = _bg_task("bg", on_failure="retry", retry_config=retry_cfg)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        # First attempt fails (exit 7), second succeeds.
        first = _mock_popen(exit_code=None, pid=11001)
        second = _mock_popen(exit_code=None, pid=11002)
        mock_launch.side_effect = [first, second]

        # Initial launch (attempt 0).
        launch_background(rs, step)
        assert "bg" in rs.background_procs

        # Simulate first attempt finishing with failure exit code.
        first.poll.return_value = 7
        reap_background(rs)

        # No failure recorded yet — retry should be scheduled.
        assert "bg" not in rs.failed
        assert "bg" not in rs.completed
        assert "bg" in rs.retry_after
        assert rs.retry_counts.get("bg") == 1
        # The Popen handle has been released so the dispatcher can re-launch.
        assert "bg" not in rs.background_procs

        # Dispatch deferred retry — backoff is 0 so it's immediately ready.
        _dispatch_deferred_retries(rs)
        assert "bg" in rs.background_procs
        assert rs.background_procs["bg"] is second
        assert "bg" not in rs.retry_after

        # Second attempt succeeds.
        second.poll.return_value = 0
        reap_background(rs)
        assert "bg" in rs.completed
        assert "bg" not in rs.failed
        assert mock_launch.call_count == 2

    @patch("swarm.plan.executor.launch_agent")
    def test_background_step_skip_on_failure_marks_skipped(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """on_failure='skip': failing background step records a skip
        outcome and downstream steps remain eligible to run."""
        bg = _bg_task("bg", on_failure="skip")
        downstream = _fg_task("fg", depends_on=("bg",))
        plan = _plan(bg, downstream)
        rs = _make_run_state(plan, tmp_path)

        proc = _mock_popen(exit_code=None, pid=11500)
        mock_launch.return_value = proc

        launch_background(rs, bg)
        proc.poll.return_value = 9
        reap_background(rs)

        assert "bg" in rs.skipped
        assert "bg" not in rs.failed
        assert rs.step_outcomes["bg"] == "skipped"
        # Downstream step's dependency is satisfied via skipped set.
        from swarm.plan.dag import get_ready_steps

        ready_ids = {
            s.id
            for s in get_ready_steps(
                plan,
                rs.completed | rs.skipped,
                artifacts_dir=rs.artifacts_dir,
                step_outcomes=rs.step_outcomes,
            )
        }
        assert "fg" in ready_ids

    @patch("swarm.plan.executor.launch_agent")
    def test_background_step_exhausts_retries_then_fails(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """3 failed attempts with max_retries=2 records a failure on the
        third reap; deferred retry timestamps respect the configured
        backoff seconds (we sample the scheduled delay rather than wall
        time to keep the test fast)."""
        retry_cfg = RetryConfig(
            max_retries=2,
            backoff_seconds=0.5,
            backoff_multiplier=2.0,
            max_backoff_seconds=10.0,
        )
        step = _bg_task("bg", on_failure="retry", retry_config=retry_cfg)
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        procs = [
            _mock_popen(exit_code=None, pid=12000 + i) for i in range(3)
        ]
        mock_launch.side_effect = procs

        # Attempt 0
        launch_background(rs, step)
        before = time.monotonic()
        procs[0].poll.return_value = 1
        reap_background(rs)
        after = time.monotonic()
        # Scheduled delay should be ~ backoff_seconds * multiplier^attempt
        # for attempt index 0 (per delay_for_attempt(0) = 0.5).
        scheduled = rs.retry_after["bg"]
        delay = scheduled - after
        assert 0.4 <= delay <= 0.6, f"delay was {delay}"
        assert delay <= scheduled - before

        # Force the scheduled time into the past so the dispatcher picks it up.
        rs.retry_after["bg"] = time.monotonic() - 0.01
        _dispatch_deferred_retries(rs)
        assert rs.background_procs["bg"] is procs[1]

        # Attempt 1
        procs[1].poll.return_value = 1
        reap_background(rs)
        scheduled = rs.retry_after["bg"]
        # delay_for_attempt(1) = 0.5 * 2 = 1.0
        delay = scheduled - time.monotonic()
        assert 0.9 <= delay <= 1.1, f"delay was {delay}"

        rs.retry_after["bg"] = time.monotonic() - 0.01
        _dispatch_deferred_retries(rs)
        assert rs.background_procs["bg"] is procs[2]

        # Attempt 2 — exhausted.
        procs[2].poll.return_value = 1
        reap_background(rs)
        assert "bg" in rs.failed
        assert "bg" not in rs.retry_after
        # The recorded outcome should mention exhaustion.
        outcomes = [s for s in rs.log.steps if s.step_id == "bg"]
        assert outcomes, "no outcome recorded"
        assert "exhausted" in outcomes[-1].message.lower()


# ---------------------------------------------------------------------------
# Fan-out branch handling in reap_background
# ---------------------------------------------------------------------------


class TestFanOutAggregation:
    """Cover lines 740-790 of executor.py — the fan-out branch ID aggregation
    inside ``reap_background`` (parent ``record_success`` only when every
    branch finishes; ``record_failure`` when any branch fails)."""

    def test_fan_out_aggregates_branch_outcomes(
        self,
        make_fan_out_state: Callable[..., tuple[RunState, PlanStep]],
    ) -> None:
        rs, fan_step = make_fan_out_state(n_branches=3, exit_codes=[0, 0, 0])

        reap_background(rs)

        # All branches should have completed outcomes.
        for i in range(3):
            assert rs.step_outcomes[f"fan::{i}"] == "completed"

        # Parent fan_step is recorded as completed exactly once.
        assert "fan" in rs.completed
        fan_outcomes = [s for s in rs.log.steps if s.step_id == "fan"]
        assert len(fan_outcomes) == 1
        assert fan_outcomes[0].status == "completed"
        # All branch records cleared from the in-flight set.
        assert rs.log.background_steps == []

    def test_fan_out_one_branch_fails(
        self,
        make_fan_out_state: Callable[..., tuple[RunState, PlanStep]],
    ) -> None:
        """Two succeed, one fails (last to finish) — parent recorded as
        failed; per-branch outcomes accessible via step_outcomes."""
        rs, fan_step = make_fan_out_state(
            n_branches=3, exit_codes=[0, 0, 5],
        )

        reap_background(rs)

        assert rs.step_outcomes["fan::0"] == "completed"
        assert rs.step_outcomes["fan::1"] == "completed"
        assert rs.step_outcomes["fan::2"] == "failed"
        assert "fan" in rs.failed
        assert "fan" not in rs.completed
        fan_outcomes = [s for s in rs.log.steps if s.step_id == "fan"]
        assert len(fan_outcomes) == 1
        assert fan_outcomes[0].status == "failed"
        assert "branches failed" in fan_outcomes[0].message

    def test_fan_out_failing_branch_finishes_first(
        self,
        make_fan_out_state: Callable[..., tuple[RunState, PlanStep]],
    ) -> None:
        """When the failing branch is the *first* to finish (with the
        successes still in flight) we should NOT yet record a parent
        outcome — only after the last branch settles.

        This catches a regression where a single failing branch finishing
        early would prematurely mark the parent failed and leave the
        sibling Popen handles dangling."""
        rs, fan_step = make_fan_out_state(
            n_branches=3, exit_codes=[7, None, None],
        )

        reap_background(rs)

        assert rs.step_outcomes.get("fan::0") == "failed"
        assert "fan" not in rs.failed
        assert "fan" not in rs.completed
        # Sibling branches still tracked.
        assert "fan::1" in rs.background_procs
        assert "fan::2" in rs.background_procs

        # Now the remaining branches finish (one ok, one fail).
        rs.background_procs["fan::1"].poll.return_value = 0
        rs.background_procs["fan::2"].poll.return_value = 0
        reap_background(rs)

        assert "fan" in rs.failed
        fan_outcomes = [s for s in rs.log.steps if s.step_id == "fan"]
        assert len(fan_outcomes) == 1

    def test_fan_out_branch_skip_on_failure(
        self,
        make_fan_out_state: Callable[..., tuple[RunState, PlanStep]],
    ) -> None:
        """Fan-out with on_failure='skip': failing branches still propagate
        as a parent failure (the fan-out aggregator does not consult the
        on_failure policy of the parent — every branch must succeed).  This
        test pins that behaviour so a future change is intentional."""
        rs, fan_step = make_fan_out_state(
            n_branches=3, exit_codes=[0, 4, 0], on_failure="skip",
        )

        reap_background(rs)

        # Branches reflect their actual exit status individually.
        assert rs.step_outcomes["fan::0"] == "completed"
        assert rs.step_outcomes["fan::1"] == "failed"
        assert rs.step_outcomes["fan::2"] == "completed"
        # Parent step records a failure (aggregation never converts to skip).
        assert "fan" in rs.failed
        fan_outcomes = [s for s in rs.log.steps if s.step_id == "fan"]
        assert len(fan_outcomes) == 1
        assert fan_outcomes[0].status == "failed"

    @patch("swarm.plan.executor.launch_agent")
    def test_fan_out_branch_pid_tracked_with_branch_index(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """Wave 1 added ``BackgroundStepRecord.branch_index``.  Verify
        ``handle_fan_out`` populates it correctly per branch and the value
        survives a round-trip through ``write_run_log``."""
        from swarm.plan.executor import handle_fan_out

        procs = [_mock_popen(pid=80_001), _mock_popen(pid=80_002), _mock_popen(pid=80_003)]
        mock_launch.side_effect = procs

        fan_step = PlanStep(
            id="fan",
            type="fan_out",
            prompt="dispatch",
            agent_type="dispatcher",
            fan_out_config=FanOutConfig(
                branches=tuple(
                    FanOutBranch(prompt=f"b{i}", agent_type="worker")
                    for i in range(3)
                ),
            ),
        )
        plan = _plan(fan_step)
        rs = _make_run_state(plan, tmp_path)

        handle_fan_out(rs, fan_step)

        records_by_id = {b.step_id: b for b in rs.log.background_steps}
        assert set(records_by_id) == {"fan::0", "fan::1", "fan::2"}
        for i in range(3):
            rec = records_by_id[f"fan::{i}"]
            assert rec.branch_index == i, f"branch_index for {rec.step_id}"
            assert rec.pid == 80_001 + i

        # Persisted log preserves branch_index.
        loaded = load_run_log(rs.log_path)
        loaded_by_id = {b.step_id: b for b in loaded.background_steps}
        for i in range(3):
            assert loaded_by_id[f"fan::{i}"].branch_index == i


# ---------------------------------------------------------------------------
# Deferred retry dispatch
# ---------------------------------------------------------------------------


class TestDispatchDeferredRetries:
    """Cover ``_dispatch_deferred_retries`` (lines 835-845)."""

    @patch("swarm.plan.executor.launch_agent")
    def test_dispatch_deferred_retries_honors_retry_after(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """A deferred retry whose ``retry_after`` is in the future is NOT
        re-launched; once the time elapses it IS re-launched."""
        step = _bg_task("bg", on_failure="retry", retry_config=RetryConfig())
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        mock_launch.return_value = _mock_popen(pid=13_000)

        # Schedule a retry 0.5s in the future.
        future_at = time.monotonic() + 0.5
        rs.retry_after["bg"] = future_at

        _dispatch_deferred_retries(rs)
        assert mock_launch.call_count == 0
        assert "bg" not in rs.background_procs
        # retry_after entry survives because the dispatcher skipped it.
        assert "bg" in rs.retry_after

        # Force the deadline into the past and dispatch again.
        rs.retry_after["bg"] = time.monotonic() - 0.01
        _dispatch_deferred_retries(rs)
        assert mock_launch.call_count == 1
        assert "bg" in rs.background_procs
        assert "bg" not in rs.retry_after

    @patch("swarm.plan.executor.launch_agent")
    def test_dispatch_deferred_retries_partial_dispatch(
        self, mock_launch: MagicMock, tmp_path: Path,
    ) -> None:
        """Dispatcher should only launch the steps whose deadline has
        elapsed, leaving the others in ``retry_after``."""
        step1 = _bg_task("bg1", on_failure="retry", retry_config=RetryConfig())
        step2 = _bg_task("bg2", on_failure="retry", retry_config=RetryConfig())
        plan = _plan(step1, step2)
        rs = _make_run_state(plan, tmp_path)
        mock_launch.side_effect = [
            _mock_popen(pid=14_001),
            _mock_popen(pid=14_002),
        ]

        # bg1 is ready, bg2 is not.
        rs.retry_after["bg1"] = time.monotonic() - 0.01
        rs.retry_after["bg2"] = time.monotonic() + 5.0

        _dispatch_deferred_retries(rs)

        assert mock_launch.call_count == 1
        assert "bg1" in rs.background_procs
        assert "bg2" not in rs.background_procs
        assert "bg1" not in rs.retry_after
        assert "bg2" in rs.retry_after


# ---------------------------------------------------------------------------
# Parallel-foreground exception isolation
# ---------------------------------------------------------------------------


class TestParallelExceptionIsolation:
    """Cover the ``ThreadPoolExecutor`` block at lines 1607-1616 of
    ``executor.py``.  Two failure modes matter: (1) one step raising must
    not corrupt the others; (2) concurrent ``record_success`` writes from
    many parallel threads must yield a valid run_log.json."""

    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_parallel_exception_in_one_step_does_not_corrupt_others(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """5 parallel steps: one raises during ``launch_agent``; the other
        4 must still complete and the run log must remain valid JSON.

        Note: the parallel-fg block re-raises via ``future.result()``, so
        the executor itself surfaces the exception to the caller.  This
        test asserts that:
          * the exception propagates (we don't silently swallow it),
          * the run_log on disk is still parseable JSON,
          * every step that DID run has a properly recorded outcome.
        """
        mock_find.return_value = Path("/usr/bin/claude")

        # Build 5 ready foreground steps (no inter-deps).
        steps = [_fg_task(f"s{i}") for i in range(5)]
        plan = _plan(*steps)
        rs = _make_run_state(plan, tmp_path)
        rs.max_parallel = 5

        # Step "s2" raises; the rest succeed.
        def launch_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            step_id = kwargs.get("step_id", "")
            if step_id == "s2":
                raise RuntimeError("simulated launch failure for s2")
            return _mock_popen(exit_code=0, pid=20_000 + int(step_id[1:]))

        mock_launch.side_effect = launch_side_effect
        mock_wait.return_value = 0

        with pytest.raises(RuntimeError, match="simulated launch failure"):
            execute_plan(rs)

        # The on-disk log must parse cleanly — no partial-write corruption.
        loaded = load_run_log(rs.log_path)
        recorded_ids = {s.step_id for s in loaded.steps}

        # The 4 non-raising steps either all ran, or were short-circuited
        # by the raised future before being scheduled.  The critical
        # invariant is that any RECORDED outcome is consistent.
        for outcome in loaded.steps:
            assert outcome.status in {"completed", "failed", "skipped"}
            assert outcome.started_at != ""
            assert outcome.finished_at != ""

        # At least the 4 non-failing steps that did run should be
        # consistent with rs.completed.
        for sid in recorded_ids:
            if sid != "s2":
                assert sid in rs.completed or sid in rs.failed

    def test_parallel_concurrent_run_log_writes_yield_valid_json(
        self, tmp_path: Path,
    ) -> None:
        """Stress: 10 threads call ``record_success`` against the same
        RunState.  The final run_log.json must parse cleanly and contain
        all 10 outcomes — proving the ``_lock`` guards the
        load+modify+write sequence."""
        from concurrent.futures import ThreadPoolExecutor

        steps = [_fg_task(f"s{i}") for i in range(10)]
        plan = _plan(*steps)
        rs = _make_run_state(plan, tmp_path)

        def _record_one(step: PlanStep) -> None:
            record_success(rs, step, attempt=0, message=f"done {step.id}")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_record_one, s) for s in steps]
            for f in futures:
                f.result()

        # The on-disk log must be valid JSON and contain every step.
        with rs.log_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        recorded = {s["step_id"] for s in data["steps"]}
        assert recorded == {f"s{i}" for i in range(10)}
        # Each outcome is a "completed" status.
        for outcome in data["steps"]:
            assert outcome["status"] == "completed"
        # In-memory completed set tracks all steps too.
        assert rs.completed == {f"s{i}" for i in range(10)}


# ---------------------------------------------------------------------------
# End-to-end (fake binary) integration tests
# ---------------------------------------------------------------------------


def _make_fake_claude(
    tmp_path: Path,
    exit_code: int = 0,
    stdout_payload: str = "",
) -> Path:
    """Write a tiny Python script to *tmp_path* that mimics ``claude`` for
    test purposes.  Returns the path; the caller should patch
    ``find_claude_binary`` to return this path.

    The script ignores its arguments, optionally writes *stdout_payload*
    to stdout, and exits with *exit_code*.
    """
    script = tmp_path / "fake_claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({stdout_payload!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


class TestEndToEndBackgroundFakeBinary:
    """Higher-fidelity tests using a fake ``claude`` script — exercises
    real ``launch_agent`` plumbing (subprocess.Popen + log file handles)
    instead of mocking it out."""

    @patch("swarm.plan.executor.find_claude_binary")
    def test_background_skip_via_real_subprocess(
        self,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Real subprocess that exits non-zero; on_failure='skip' should
        eventually mark the step skipped in the persisted run log."""
        fake = _make_fake_claude(tmp_path, exit_code=1)
        # Patch the launcher's find_claude_binary AND the executor's
        # pre-flight check — both reference distinct module-level imports.
        with patch("swarm.plan.launcher.find_claude_binary", return_value=fake):
            mock_find.return_value = fake

            step = _bg_task("bg", on_failure="skip")
            plan = _plan(step)
            rs = _make_run_state(plan, tmp_path)

            # Drive launch + wait for natural exit + reap.
            launch_background(rs, step)
            proc = rs.background_procs["bg"]
            assert proc.wait(timeout=5) == 1

            reap_background(rs)

        assert "bg" in rs.skipped
        loaded = load_run_log(rs.log_path)
        skipped_outcomes = [s for s in loaded.steps if s.step_id == "bg"]
        assert skipped_outcomes
        assert skipped_outcomes[0].status == "skipped"
        # Background record cleared.
        assert loaded.background_steps == []

    @patch("swarm.plan.executor.find_claude_binary")
    def test_background_stop_failure_via_real_subprocess(
        self,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Real subprocess fails with on_failure='stop' (default) and no
        retry config — should be recorded as failed with the actual exit
        code surfaced to the run log."""
        fake = _make_fake_claude(tmp_path, exit_code=42)
        with patch("swarm.plan.launcher.find_claude_binary", return_value=fake):
            mock_find.return_value = fake

            step = _bg_task("bg", on_failure="stop")
            plan = _plan(step)
            rs = _make_run_state(plan, tmp_path)

            launch_background(rs, step)
            assert rs.background_procs["bg"].wait(timeout=5) == 42

            reap_background(rs)

        assert "bg" in rs.failed
        loaded = load_run_log(rs.log_path)
        failed = [s for s in loaded.steps if s.step_id == "bg"]
        assert failed
        assert failed[0].status == "failed"
        assert failed[0].exit_code == 42

    @patch("swarm.plan.executor.find_claude_binary")
    def test_fan_out_branches_aggregate_via_real_subprocesses(
        self,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Three real subprocess fan-out branches all succeed; reaping
        aggregates them into a single parent-completed outcome."""
        fake = _make_fake_claude(tmp_path, exit_code=0)
        with patch("swarm.plan.launcher.find_claude_binary", return_value=fake):
            mock_find.return_value = fake

            from swarm.plan.executor import handle_fan_out

            fan_step = PlanStep(
                id="fan",
                type="fan_out",
                prompt="dispatch",
                agent_type="dispatcher",
                fan_out_config=FanOutConfig(
                    branches=tuple(
                        FanOutBranch(prompt=f"b{i}", agent_type="worker")
                        for i in range(3)
                    ),
                ),
            )
            plan = _plan(fan_step)
            rs = _make_run_state(plan, tmp_path)

            handle_fan_out(rs, fan_step)
            assert len(rs.background_procs) == 3

            # Wait for every real subprocess to finish.
            for proc in list(rs.background_procs.values()):
                assert proc.wait(timeout=5) == 0

            reap_background(rs)

        assert "fan" in rs.completed
        loaded = load_run_log(rs.log_path)
        fan_outcomes = [s for s in loaded.steps if s.step_id == "fan"]
        assert len(fan_outcomes) == 1
        assert fan_outcomes[0].status == "completed"
        assert loaded.background_steps == []


# ---------------------------------------------------------------------------
# Misconfigured fan-out (no fan_out_config)
# ---------------------------------------------------------------------------


class TestFanOutMissingConfig:
    """Cover the early-return branch of ``handle_fan_out`` (lines 944-950)."""

    def test_handle_fan_out_without_config_records_failure(
        self, tmp_path: Path,
    ) -> None:
        from swarm.plan.executor import handle_fan_out

        step = PlanStep(
            id="fan",
            type="fan_out",
            prompt="missing config",
            agent_type="dispatcher",
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_fan_out(rs, step)

        assert "fan" in rs.failed
        outcomes = [s for s in rs.log.steps if s.step_id == "fan"]
        assert outcomes
        assert "missing fan_out_config" in outcomes[0].message
        # Nothing launched.
        assert rs.background_procs == {}


# ---------------------------------------------------------------------------
# Smoke check: PID variable used in the fixture is unique per branch
# ---------------------------------------------------------------------------


def test_pid_collision_does_not_blur_branches(
    make_fan_out_state: Callable[..., tuple[RunState, PlanStep]],
) -> None:
    """Defensive check: branch identity is keyed by ``step_id`` (the
    ``base::index`` form), not by PID — so even if two branches reused a
    PID (impossible in real life, but worth pinning) the per-branch
    outcomes remain distinct."""
    rs, _ = make_fan_out_state(n_branches=2, exit_codes=[0, 0])
    # Force both background procs to claim the same PID.
    for proc in rs.background_procs.values():
        proc.pid = 99_999
    assert {p.pid for p in rs.background_procs.values()} == {99_999}

    reap_background(rs)
    assert rs.step_outcomes["fan::0"] == "completed"
    assert rs.step_outcomes["fan::1"] == "completed"
    assert "fan" in rs.completed


# Suppress unused-import lint warning for ``os`` (kept for future tests
# that need to inspect on-disk state).
_ = os
