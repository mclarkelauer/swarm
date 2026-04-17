"""Tests for distributed tracing in the plan executor (Tier 5).

Asserts the actual current behavior of:
    * ``_trace_env`` — produces SWARM_TRACE_ID + SWARM_SPAN_ID env vars.
    * Subprocess env propagation — fake-binary pattern verifies the
      trace ID lands in the agent process's environment.
    * ``finalize`` — surfaces the trace_id in the run summary.

Documented gaps (asserted as ``xfail`` so future fixes auto-clear):
    * Trace ID is NOT persisted in :class:`RunLog`, so it's lost on
      resume.  See :class:`TestTraceIdResumeBehavior`.
    * Subplan execution mints a fresh trace ID rather than inheriting
      or recording the parent.  See :class:`TestTraceIdSubplanBehavior`.
"""

from __future__ import annotations

import json
import stat
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.plan.executor import (
    RunState,
    _trace_env,
    execute_plan,
    finalize,
    init_run_state,
)
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, write_run_log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep, variables: dict[str, str] | None = None) -> Plan:
    return Plan(
        version=1,
        goal="trace test plan",
        steps=list(steps),
        variables=variables or {},
    )


def _make_run_state(
    plan: Plan,
    tmp_path: Path,
    *,
    trace_id: str = "fixed-trace-id-1234",
) -> RunState:
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
        trace_id=trace_id,
    )


def _write_fake_claude(
    tmp_path: Path,
    out_path: Path,
    env_var: str = "SWARM_TRACE_ID",
) -> Path:
    """Write a fake "claude" binary that records ``env_var`` to *out_path*.

    The fake binary parses just enough argv to find the ``-p`` (step prompt)
    flag and ignores everything else.  It writes an ``--output-format json``
    blob to stdout so ``_parse_cost_data`` won't complain about silent zeros.
    """
    fake = tmp_path / "fake_claude"
    out_str = str(out_path)
    script = (
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"out = {out_str!r}\n"
        f"with open(out, 'a', encoding='utf-8') as f:\n"
        f"    f.write(os.environ.get({env_var!r}, '') + chr(10))\n"
        # Emit a minimal --output-format json shaped result so the executor's
        # cost parser doesn't log warnings.
        "result = {'usage': {'input_tokens': 0, 'output_tokens': 0}}\n"
        "sys.stdout.write(json.dumps(result))\n"
        "sys.exit(0)\n"
    )
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


# ---------------------------------------------------------------------------
# _trace_env
# ---------------------------------------------------------------------------


class TestTraceEnv:
    def test_includes_trace_and_span_id(self, tmp_path: Path) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path, trace_id="abc-123")

        env = _trace_env(rs, step)
        assert env["SWARM_TRACE_ID"] == "abc-123"
        assert env["SWARM_SPAN_ID"] == "abc-123:s1"

    def test_empty_trace_id_yields_empty_env(self, tmp_path: Path) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path, trace_id="")

        env = _trace_env(rs, step)
        assert env == {}

    def test_span_id_is_unique_per_step(self, tmp_path: Path) -> None:
        s1 = PlanStep(id="alpha", type="task", prompt="p")
        s2 = PlanStep(id="beta", type="task", prompt="p")
        plan = _plan(s1, s2)
        rs = _make_run_state(plan, tmp_path, trace_id="trace-XYZ")

        env_a = _trace_env(rs, s1)
        env_b = _trace_env(rs, s2)
        assert env_a["SWARM_SPAN_ID"] != env_b["SWARM_SPAN_ID"]
        assert env_a["SWARM_TRACE_ID"] == env_b["SWARM_TRACE_ID"]

    def test_init_run_state_assigns_uuid_trace_id(self, tmp_path: Path) -> None:
        """A fresh run_state has a parseable UUID trace_id."""
        plan = _plan(PlanStep(id="s1", type="task", prompt="p"))
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        rs = init_run_state(
            plan,
            plan_path,
            tmp_path / "artifacts",
            tmp_path / "run_log.json",
        )

        # Should round-trip through uuid.UUID without raising.
        parsed = uuid.UUID(rs.trace_id)
        assert str(parsed) == rs.trace_id


# ---------------------------------------------------------------------------
# Subprocess env propagation (end-to-end via fake binary)
# ---------------------------------------------------------------------------


class TestTraceIdSubprocessPropagation:
    def test_trace_id_propagates_to_subprocess(self, tmp_path: Path) -> None:
        """A 1-step plan executed end-to-end propagates SWARM_TRACE_ID
        into the agent subprocess's env.

        The fake "claude" binary writes whatever it sees in ``SWARM_TRACE_ID``
        to a sidecar file.  We assert that file contains the parent's
        trace_id after the run.
        """
        env_capture = tmp_path / "trace_capture.txt"
        fake_claude = _write_fake_claude(tmp_path, env_capture)

        plan = _plan(
            PlanStep(
                id="s1",
                type="task",
                prompt="do thing",
                agent_type="worker",
            ),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        with patch(
            "swarm.plan.launcher.shutil.which", return_value=str(fake_claude),
        ):
            rs = init_run_state(
                plan,
                plan_path,
                tmp_path / "artifacts",
                tmp_path / "run_log.json",
            )
            # Pin the trace_id so we can assert against a known value.
            rs.trace_id = "deadbeef-trace-id"
            result = execute_plan(rs)

        assert result["status"] == "completed"
        assert env_capture.exists(), "Fake claude binary was never invoked"
        captured = env_capture.read_text(encoding="utf-8").strip().splitlines()
        assert "deadbeef-trace-id" in captured

    def test_span_id_propagates_to_subprocess(self, tmp_path: Path) -> None:
        """SWARM_SPAN_ID also lands in the subprocess env."""
        env_capture = tmp_path / "span_capture.txt"
        fake_claude = _write_fake_claude(
            tmp_path, env_capture, env_var="SWARM_SPAN_ID",
        )

        plan = _plan(
            PlanStep(
                id="step-with-id",
                type="task",
                prompt="do thing",
                agent_type="worker",
            ),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        with patch(
            "swarm.plan.launcher.shutil.which", return_value=str(fake_claude),
        ):
            rs = init_run_state(
                plan,
                plan_path,
                tmp_path / "artifacts",
                tmp_path / "run_log.json",
            )
            rs.trace_id = "trace-AAA"
            execute_plan(rs)

        captured = env_capture.read_text(encoding="utf-8").strip().splitlines()
        assert "trace-AAA:step-with-id" in captured


# ---------------------------------------------------------------------------
# finalize summary
# ---------------------------------------------------------------------------


class TestFinalizeIncludesTraceId:
    def test_trace_id_in_finalize_summary(self, tmp_path: Path) -> None:
        plan = _plan(PlanStep(id="s1", type="task", prompt="p"))
        rs = _make_run_state(plan, tmp_path, trace_id="finalize-trace-id")

        summary = finalize(rs, "completed")
        assert summary["trace_id"] == "finalize-trace-id"

    def test_finalize_summary_when_trace_id_missing(self, tmp_path: Path) -> None:
        """An empty trace_id round-trips through finalize as empty string."""
        plan = _plan(PlanStep(id="s1", type="task", prompt="p"))
        rs = _make_run_state(plan, tmp_path, trace_id="")

        summary = finalize(rs, "completed")
        assert summary["trace_id"] == ""


# ---------------------------------------------------------------------------
# Resume behavior — currently NOT preserved across resume.
# ---------------------------------------------------------------------------


class TestTraceIdResumeBehavior:
    def test_trace_id_not_assigned_on_resume(self, tmp_path: Path) -> None:
        """Document current behavior: resume does NOT restore trace_id.

        ``init_run_state`` only assigns a UUID trace_id on the *fresh-run*
        branch.  The resume branch leaves it as the dataclass default ``""``.

        This is asserted as the current (broken) behavior so a future fix
        that wires trace_id into :class:`RunLog` will surface as a deliberate
        test update rather than a silent regression.
        """
        plan = _plan(
            PlanStep(id="s1", type="task", prompt="p", agent_type="worker"),
            PlanStep(
                id="s2", type="task", prompt="p", agent_type="worker",
                depends_on=("s1",),
            ),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # First init: fresh run gets a real trace_id.
        rs1 = init_run_state(plan, plan_path, artifacts_dir, log_path)
        original_trace = rs1.trace_id
        assert original_trace, "fresh run should have a trace_id"

        # Persist some progress so the second init takes the resume branch.
        from swarm.plan.run_log import StepOutcome

        rs1.log.steps.append(
            StepOutcome(
                step_id="s1",
                status="completed",
                started_at="t0",
                finished_at="t1",
            ),
        )
        write_run_log(rs1.log, log_path)

        # Second init: resume.  Current behavior: trace_id reverts to "".
        rs2 = init_run_state(plan, plan_path, artifacts_dir, log_path)

        # Document current behavior loudly.
        assert rs2.trace_id == "", (
            "Current behavior: resume does NOT restore trace_id. "
            "If this assertion now fails, a fix has landed — update the test "
            "to assert rs2.trace_id == original_trace."
        )

    @pytest.mark.xfail(
        reason=(
            "Trace ID is not persisted in RunLog, so it's regenerated "
            "(actually, lost) on resume.  Tracking issue: wire trace_id "
            "into RunLog so distributed traces survive resume."
        ),
        strict=True,
    )
    def test_run_state_trace_id_is_stable_across_resume(
        self,
        tmp_path: Path,
    ) -> None:
        """Aspirational: trace_id should be stable across resume.

        Currently fails because RunLog has no trace_id field.
        """
        plan = _plan(
            PlanStep(id="s1", type="task", prompt="p", agent_type="worker"),
            PlanStep(
                id="s2", type="task", prompt="p", agent_type="worker",
                depends_on=("s1",),
            ),
        )
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        log_path = tmp_path / "run_log.json"
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        rs1 = init_run_state(plan, plan_path, artifacts_dir, log_path)
        original_trace = rs1.trace_id

        from swarm.plan.run_log import StepOutcome

        rs1.log.steps.append(
            StepOutcome(
                step_id="s1",
                status="completed",
                started_at="t0",
                finished_at="t1",
            ),
        )
        write_run_log(rs1.log, log_path)

        rs2 = init_run_state(plan, plan_path, artifacts_dir, log_path)
        assert rs2.trace_id == original_trace


# ---------------------------------------------------------------------------
# Subplan trace_id behavior
# ---------------------------------------------------------------------------


class TestTraceIdSubplanBehavior:
    @pytest.mark.xfail(
        reason=(
            "Subplan execution mints a fresh trace_id via init_run_state "
            "rather than inheriting from the parent or recording it as "
            "parent_trace_id.  No structural support for distributed "
            "trace propagation across subplans yet."
        ),
        strict=True,
    )
    def test_trace_id_propagates_to_subplan(self, tmp_path: Path) -> None:
        """Aspirational: child sub-plan should inherit (or record) the parent
        trace_id.

        Currently fails because ``handle_subplan`` only inherits ``memory_api``
        and the subplan's ``init_run_state`` mints a brand-new UUID.
        """
        # Build a sub-plan with one step.
        sub_plan_data = {
            "version": 1,
            "goal": "sub",
            "steps": [
                {
                    "id": "inner",
                    "type": "task",
                    "prompt": "inner",
                    "agent_type": "worker",
                },
            ],
        }
        sub_path = tmp_path / "sub.json"
        sub_path.write_text(json.dumps(sub_plan_data), encoding="utf-8")

        # Capture the trace_id that the sub-plan ends up with.
        captured_traces: list[str] = []

        from swarm.plan import executor as exec_mod

        original_init = exec_mod.init_run_state

        def _spy_init(*args: Any, **kwargs: Any) -> RunState:
            rs = original_init(*args, **kwargs)
            captured_traces.append(rs.trace_id)
            return rs

        parent_step = PlanStep(
            id="sub_step",
            type="subplan",
            prompt="run subplan",
            subplan_path=str(sub_path),
        )
        plan = _plan(parent_step)
        rs = _make_run_state(plan, tmp_path, trace_id="parent-trace-id")

        # Mock out the agent subprocess so we don't actually fork claude.
        with (
            patch("swarm.plan.executor.find_claude_binary"),
            patch("swarm.plan.executor.launch_agent") as mock_launch,
            patch("swarm.plan.executor.wait_with_timeout", return_value=0),
            patch("swarm.plan.executor.init_run_state", side_effect=_spy_init),
        ):
            mock_launch.return_value = MagicMock(
                pid=12345,
                poll=MagicMock(return_value=0),
                wait=MagicMock(return_value=0),
            )
            from swarm.plan.executor import handle_subplan

            handle_subplan(rs, parent_step)

        # The sub-RunState's trace_id should match the parent or record it
        # as a parent_trace_id.  Currently it's a fresh UUID.
        assert captured_traces, "init_run_state was never called for subplan"
        sub_trace = captured_traces[-1]
        assert sub_trace == "parent-trace-id"


# ---------------------------------------------------------------------------
# Smoke test: ensure the trace env block doesn't pollute existing env keys.
# ---------------------------------------------------------------------------


class TestTraceEnvIsAdditiveOnly:
    def test_trace_env_only_returns_swarm_keys(self, tmp_path: Path) -> None:
        """``_trace_env`` only emits SWARM_-prefixed keys."""
        plan = _plan(PlanStep(id="s", type="task", prompt="p"))
        rs = _make_run_state(plan, tmp_path, trace_id="t")
        step = plan.steps[0]
        env = _trace_env(rs, step)
        assert all(key.startswith("SWARM_") for key in env)
