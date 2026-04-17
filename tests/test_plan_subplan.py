"""Tests for subplan step execution.

Originally only 5 thin tests; extended to cover:
    * Failure propagation from sub-plan steps to the parent step.
    * memory_api inheritance into the sub-RunState.
    * Relative subplan_path resolution against the parent's artifacts_dir.
    * Self-reference / unbounded recursion (currently unprotected — xfail).
    * Sub-run-log path capture in the parent's StepOutcome (currently
      message-only — xfail).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarm.memory.api import MemoryAPI
from swarm.plan.executor import (
    RunState,
    handle_subplan,
)
from swarm.plan.models import Plan, PlanStep
from swarm.plan.run_log import RunLog, write_run_log

# ---------------------------------------------------------------------------
# Helpers (mirrored from test_plan_executor.py)
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep, variables: dict[str, str] | None = None) -> Plan:
    return Plan(
        version=1,
        goal="test plan",
        steps=list(steps),
        variables=variables or {},
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


def _write_subplan(
    path: Path,
    *,
    inner_id: str = "inner",
    on_failure: str = "stop",
    extra: dict[str, Any] | None = None,
) -> Path:
    sub_plan: dict[str, Any] = {
        "version": 1,
        "goal": "sub",
        "steps": [
            {
                "id": inner_id,
                "type": "task",
                "prompt": "do inner work",
                "agent_type": "worker",
                "on_failure": on_failure,
            },
        ],
    }
    if extra:
        sub_plan.update(extra)
    path.write_text(json.dumps(sub_plan), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Original tests (preserved)
# ---------------------------------------------------------------------------


class TestSubplan:
    def test_subplan_missing_path_fails(self, tmp_path: Path) -> None:
        step = PlanStep(id="sub1", type="subplan", prompt="nested")
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.failed

    def test_subplan_file_not_found_fails(self, tmp_path: Path) -> None:
        step = PlanStep(
            id="sub1", type="subplan", prompt="nested",
            subplan_path="/nonexistent.json",
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.failed

    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_success(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        sub_path = _write_subplan(tmp_path / "sub_plan.json")

        step = PlanStep(
            id="sub1", type="subplan", prompt="nested",
            subplan_path=str(sub_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)
        handle_subplan(rs, step)
        assert "sub1" in rs.completed

    def test_subplan_path_in_to_dict(self) -> None:
        step = PlanStep(id="s1", type="subplan", prompt="p", subplan_path="sub.json")
        d = step.to_dict()
        assert d["subplan_path"] == "sub.json"

    def test_subplan_path_not_in_to_dict_when_empty(self) -> None:
        step = PlanStep(id="s1", type="task", prompt="p")
        d = step.to_dict()
        assert "subplan_path" not in d


# ---------------------------------------------------------------------------
# New: Failure propagation
# ---------------------------------------------------------------------------


class TestSubplanFailurePropagation:
    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_failure_marks_parent_failed(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If a sub-plan step fails (on_failure=stop), the parent's subplan
        step is recorded as failed and parent.failed contains the step id."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=999,
            poll=MagicMock(return_value=1),
            wait=MagicMock(return_value=1),
        )
        # Inner step will fail.
        mock_wait.return_value = 1

        sub_path = _write_subplan(
            tmp_path / "fail_subplan.json",
            inner_id="inner_fail",
            on_failure="stop",
        )

        parent_step = PlanStep(
            id="parent_sub",
            type="subplan",
            prompt="run failing sub",
            subplan_path=str(sub_path),
        )
        plan = _plan(parent_step)
        rs = _make_run_state(plan, tmp_path)

        handle_subplan(rs, parent_step)

        assert "parent_sub" in rs.failed
        assert rs.step_outcomes["parent_sub"] == "failed"

        # The parent's StepOutcome message should reference the failed inner
        # step id so operators can drill in without rummaging through the
        # sub-run-log.
        parent_outcome = next(
            o for o in rs.log.steps if o.step_id == "parent_sub"
        )
        assert parent_outcome.status == "failed"
        assert "inner_fail" in parent_outcome.message


# ---------------------------------------------------------------------------
# New: memory_api inheritance
# ---------------------------------------------------------------------------


class TestSubplanMemoryInheritance:
    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_inherits_memory_api(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Memories stored before the sub-plan runs should be recall-able
        from the inner agents — i.e. the sub-RunState reuses the parent's
        :class:`MemoryAPI`."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        sub_path = _write_subplan(tmp_path / "sub_with_mem.json")

        with MemoryAPI(tmp_path / "mem.db") as memory:
            memory.store(
                agent_name="worker",
                content="parent-stored fact",
                memory_type="semantic",
            )

            parent_step = PlanStep(
                id="sub_step",
                type="subplan",
                prompt="run subplan",
                subplan_path=str(sub_path),
            )
            plan = _plan(parent_step)
            rs = _make_run_state(plan, tmp_path)
            rs.memory_api = memory

            # Capture the sub-RunState by spying on init_run_state.
            captured: dict[str, RunState] = {}
            from swarm.plan import executor as exec_mod

            original_init = exec_mod.init_run_state

            def _spy_init(*args: Any, **kwargs: Any) -> RunState:
                state = original_init(*args, **kwargs)
                captured["sub"] = state
                return state

            with patch(
                "swarm.plan.executor.init_run_state", side_effect=_spy_init,
            ):
                handle_subplan(rs, parent_step)

            sub_state = captured["sub"]
            assert sub_state.memory_api is memory, (
                "Sub-RunState should inherit the parent's MemoryAPI"
            )
            recalled = sub_state.memory_api.recall(agent_name="worker")
            contents = [m.content for m in recalled]
            assert "parent-stored fact" in contents


# ---------------------------------------------------------------------------
# New: relative path resolution
# ---------------------------------------------------------------------------


class TestSubplanPathResolution:
    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_relative_path_resolves_against_artifacts_dir(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A relative ``subplan_path`` resolves against the parent's
        artifacts_dir, not the process cwd."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        plan = _plan(
            PlanStep(
                id="sub_step",
                type="subplan",
                prompt="nested",
                subplan_path="nested/sub.json",  # relative
            ),
        )
        rs = _make_run_state(plan, tmp_path)

        # Place the subplan file under artifacts_dir/nested/, NOT under cwd.
        nested_dir = rs.artifacts_dir / "nested"
        nested_dir.mkdir(parents=True, exist_ok=True)
        _write_subplan(nested_dir / "sub.json")

        # Move cwd somewhere where the relative path would NOT resolve.
        decoy_cwd = tmp_path / "decoy"
        decoy_cwd.mkdir()
        monkeypatch.chdir(decoy_cwd)

        handle_subplan(rs, plan.steps[0])

        # If resolution were relative to cwd, the subplan file wouldn't be
        # found and the step would be marked failed with "not found".
        assert "sub_step" in rs.completed, (
            f"Expected resolution against artifacts_dir; got: "
            f"{[(o.step_id, o.status, o.message) for o in rs.log.steps]}"
        )

    def test_subplan_absolute_path_used_verbatim(self, tmp_path: Path) -> None:
        """Absolute paths bypass the artifacts_dir resolution."""
        # Place a subplan at a known absolute location and verify the
        # resolution branch picks it up.  We don't need to execute it —
        # just confirm that the not-found branch isn't taken.
        sub_path = tmp_path / "abs_sub.json"
        _write_subplan(sub_path)
        assert sub_path.is_absolute()

        with (
            patch("swarm.plan.executor.find_claude_binary"),
            patch("swarm.plan.executor.launch_agent") as mock_launch,
            patch("swarm.plan.executor.wait_with_timeout", return_value=0),
        ):
            mock_launch.return_value = MagicMock(
                pid=1,
                poll=MagicMock(return_value=0),
                wait=MagicMock(return_value=0),
            )
            step = PlanStep(
                id="sub_step",
                type="subplan",
                prompt="nested",
                subplan_path=str(sub_path),
            )
            plan = _plan(step)
            rs = _make_run_state(plan, tmp_path)
            handle_subplan(rs, step)

        assert "sub_step" in rs.completed


# ---------------------------------------------------------------------------
# New: parent run log captures sub-run details
# ---------------------------------------------------------------------------


class TestSubplanParentRunLog:
    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_subplan_completed_in_parent_run_log(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Parent run_log.steps must include the subplan step with
        status='completed' once the sub-plan returns."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        sub_path = _write_subplan(tmp_path / "sub_log_test.json")

        step = PlanStep(
            id="parent_sub",
            type="subplan",
            prompt="nested",
            subplan_path=str(sub_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_subplan(rs, step)

        outcomes = [o for o in rs.log.steps if o.step_id == "parent_sub"]
        assert len(outcomes) == 1
        assert outcomes[0].status == "completed"

    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_sub_run_log_file_is_written(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """The sub-RunState writes its own run_log.json so ``swarm trace``
        / ``swarm status`` can inspect the inner run later."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        sub_path = _write_subplan(tmp_path / "sub.json")

        step = PlanStep(
            id="parent_sub",
            type="subplan",
            prompt="nested",
            subplan_path=str(sub_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_subplan(rs, step)

        # handle_subplan writes the sub-run log to:
        #   <artifacts_dir>/subplan_<step_id>/run_log.json
        sub_log = rs.artifacts_dir / f"subplan_{step.id}" / "run_log.json"
        assert sub_log.exists(), (
            f"Sub-run log not found at {sub_log}; artifacts_dir contents: "
            f"{list(rs.artifacts_dir.rglob('*'))}"
        )
        # Spot-check the content is a valid run log.
        data = json.loads(sub_log.read_text(encoding="utf-8"))
        assert data["plan_path"]
        assert "steps" in data

    @pytest.mark.xfail(
        reason=(
            "handle_subplan does not record the sub-run-log path on the "
            "parent's StepOutcome — the message field carries only a step "
            "count.  Future fix: capture sub_log_path so `swarm trace` can "
            "deep-link to the inner run."
        ),
        strict=True,
    )
    @patch("swarm.plan.executor.find_claude_binary")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.wait_with_timeout")
    def test_parent_outcome_records_sub_run_log_path(
        self,
        mock_wait: MagicMock,
        mock_launch: MagicMock,
        mock_find: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Aspirational: the parent's StepOutcome.message (or a future
        dedicated field) should reference the sub-run-log path."""
        mock_find.return_value = Path("/usr/bin/claude")
        mock_launch.return_value = MagicMock(
            pid=123,
            poll=MagicMock(return_value=0),
            wait=MagicMock(return_value=0),
        )
        mock_wait.return_value = 0

        sub_path = _write_subplan(tmp_path / "sub.json")

        step = PlanStep(
            id="parent_sub",
            type="subplan",
            prompt="nested",
            subplan_path=str(sub_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        handle_subplan(rs, step)

        outcome = next(o for o in rs.log.steps if o.step_id == "parent_sub")
        # Currently fails: message is "Subplan completed: 1 steps" with no
        # path reference.
        assert "run_log.json" in outcome.message


# ---------------------------------------------------------------------------
# New: self-reference / recursion bound
# ---------------------------------------------------------------------------


class TestSubplanRecursionBound:
    @pytest.mark.xfail(
        reason=(
            "No recursion bound in handle_subplan — a subplan that "
            "references its own parent (or a cycle of any depth) will "
            "recurse until the OS kills the process.  Future fix: add a "
            "max_subplan_depth (e.g. 10) and reject self-references."
        ),
        strict=True,
    )
    def test_subplan_self_reference_is_rejected_or_caught(
        self,
        tmp_path: Path,
    ) -> None:
        """Aspirational: a subplan that points at the parent plan should be
        rejected at validation time or caught by a recursion guard."""
        # Create a "subplan" file that itself contains a subplan step
        # pointing back at itself.
        self_ref_path = tmp_path / "self_ref.json"
        self_referencing = {
            "version": 1,
            "goal": "self-ref",
            "steps": [
                {
                    "id": "loop_back",
                    "type": "subplan",
                    "prompt": "back-ref",
                    "subplan_path": str(self_ref_path),
                },
            ],
        }
        self_ref_path.write_text(
            json.dumps(self_referencing), encoding="utf-8",
        )

        # Build a parent plan that invokes the self-referencing file.
        step = PlanStep(
            id="parent_sub",
            type="subplan",
            prompt="invoke self-ref",
            subplan_path=str(self_ref_path),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        # Try the call with a small depth budget so the test doesn't blow
        # the stack if the bound is missing.  Currently this RecursionError
        # surfaces — the xfail is because we want the executor to surface
        # a clean failure rather than a Python RecursionError.
        try:
            with patch(
                "swarm.plan.executor.find_claude_binary",
            ):
                handle_subplan(rs, step)
        except RecursionError:
            # Surface as test failure — xfail catches it.
            pytest.fail(
                "Unbounded recursion: handle_subplan did not detect the "
                "self-reference and let Python's recursion limit fire.",
            )

        # When bounded, the parent step should be marked failed with a
        # message referencing the recursion / depth bound.
        assert "parent_sub" in rs.failed
        outcome = next(o for o in rs.log.steps if o.step_id == "parent_sub")
        assert "recursion" in outcome.message.lower() or (
            "depth" in outcome.message.lower()
        )
