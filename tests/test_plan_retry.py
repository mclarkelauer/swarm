"""Tests for retry logic in swarm.plan.executor and swarm.plan.models.RetryConfig."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from swarm.plan.executor import (
    RunState,
    execute_foreground,
    execute_plan,
)
from swarm.plan.models import Plan, PlanStep, RetryConfig
from swarm.plan.run_log import RunLog, write_run_log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(*steps: PlanStep) -> Plan:
    return Plan(version=1, goal="test", steps=list(steps))


def _make_run_state(plan: Plan, tmp_path: Path) -> RunState:
    log_path = tmp_path / "run_log.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(
        plan_path=str(tmp_path / "plan.json"),
        plan_version=1,
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


def _mock_popen(exit_code: int = 0) -> MagicMock:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 12345
    proc.wait.return_value = exit_code
    proc.poll.return_value = None
    return proc


# ---------------------------------------------------------------------------
# RetryConfig model tests
# ---------------------------------------------------------------------------


class TestRetryConfigRoundtrip:
    def test_roundtrip_defaults(self) -> None:
        rc = RetryConfig()
        d = rc.to_dict()
        restored = RetryConfig.from_dict(d)
        assert restored.max_retries == 3
        assert restored.backoff_seconds == 2.0
        assert restored.backoff_multiplier == 2.0
        assert restored.max_backoff_seconds == 60.0

    def test_roundtrip_custom(self) -> None:
        rc = RetryConfig(
            max_retries=5,
            backoff_seconds=1.0,
            backoff_multiplier=3.0,
            max_backoff_seconds=120.0,
        )
        d = rc.to_dict()
        restored = RetryConfig.from_dict(d)
        assert restored.max_retries == 5
        assert restored.backoff_seconds == 1.0
        assert restored.backoff_multiplier == 3.0
        assert restored.max_backoff_seconds == 120.0


class TestRetryConfigSparseSerialization:
    def test_all_defaults_produce_empty_dict(self) -> None:
        rc = RetryConfig()
        d = rc.to_dict()
        assert d == {}

    def test_only_non_default_fields_emitted(self) -> None:
        rc = RetryConfig(max_retries=5)
        d = rc.to_dict()
        assert d == {"max_retries": 5}
        assert "backoff_seconds" not in d
        assert "backoff_multiplier" not in d
        assert "max_backoff_seconds" not in d

    def test_step_with_retry_config_all_defaults_omits_key(self) -> None:
        """When retry_config has all-default values, the step to_dict omits it."""
        step = PlanStep(
            id="s1",
            type="task",
            prompt="p",
            agent_type="w",
            on_failure="retry",
            retry_config=RetryConfig(),
        )
        d = step.to_dict()
        # RetryConfig() produces empty dict, so to_dict skips it
        assert "retry_config" not in d


class TestRetryConfigDelayCalculation:
    def test_first_attempt_delay(self) -> None:
        rc = RetryConfig(backoff_seconds=2.0, backoff_multiplier=2.0)
        assert rc.delay_for_attempt(0) == 2.0

    def test_second_attempt_delay(self) -> None:
        rc = RetryConfig(backoff_seconds=2.0, backoff_multiplier=2.0)
        assert rc.delay_for_attempt(1) == 4.0

    def test_third_attempt_delay(self) -> None:
        rc = RetryConfig(backoff_seconds=2.0, backoff_multiplier=2.0)
        assert rc.delay_for_attempt(2) == 8.0

    def test_delay_respects_max_backoff(self) -> None:
        rc = RetryConfig(
            backoff_seconds=10.0,
            backoff_multiplier=10.0,
            max_backoff_seconds=30.0,
        )
        # Attempt 2: 10 * 10^2 = 1000, but capped at 30
        assert rc.delay_for_attempt(2) == 30.0

    def test_delay_exactly_at_max_backoff(self) -> None:
        rc = RetryConfig(
            backoff_seconds=5.0,
            backoff_multiplier=2.0,
            max_backoff_seconds=20.0,
        )
        # Attempt 2: 5 * 2^2 = 20, exactly at max
        assert rc.delay_for_attempt(2) == 20.0


class TestRetryConfigAutoCreated:
    def test_auto_created_when_on_failure_retry(self) -> None:
        """PlanStep.from_dict auto-creates RetryConfig when on_failure is 'retry'."""
        d = {
            "id": "s1",
            "type": "task",
            "prompt": "p",
            "agent_type": "w",
            "on_failure": "retry",
        }
        step = PlanStep.from_dict(d)
        assert step.retry_config is not None
        assert step.retry_config.max_retries == 3

    def test_not_auto_created_when_on_failure_stop(self) -> None:
        d = {
            "id": "s1",
            "type": "task",
            "prompt": "p",
            "agent_type": "w",
            "on_failure": "stop",
        }
        step = PlanStep.from_dict(d)
        assert step.retry_config is None


# ---------------------------------------------------------------------------
# execute_foreground retry tests
# ---------------------------------------------------------------------------


class TestExecuteForegroundRetries:
    @patch("swarm.plan.executor.time.sleep")
    @patch("swarm.plan.executor.launch_agent")
    def test_retries_on_failure(
        self,
        mock_launch: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        """First call fails, second succeeds -- should retry once."""
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_popen(exit_code=1)
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _side_effect

        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            on_failure="retry",
            retry_config=RetryConfig(max_retries=3, backoff_seconds=0.01),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        execute_foreground(rs, step)

        assert "s1" in rs.completed
        assert mock_launch.call_count == 2
        mock_sleep.assert_called_once()

    @patch("swarm.plan.executor.time.sleep")
    @patch("swarm.plan.executor.launch_agent")
    def test_exhausts_retries_then_fails(
        self,
        mock_launch: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        """All attempts fail -- should record failure after exhausting retries."""
        mock_launch.return_value = _mock_popen(exit_code=1)

        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            on_failure="retry",
            retry_config=RetryConfig(max_retries=2, backoff_seconds=0.01),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        execute_foreground(rs, step)

        assert "s1" in rs.failed
        # 1 initial + 2 retries = 3 total calls
        assert mock_launch.call_count == 3

    @patch("swarm.plan.executor.time.sleep")
    @patch("swarm.plan.executor.launch_agent")
    def test_retry_records_attempt_number_in_outcome(
        self,
        mock_launch: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After exhausting retries, the last attempt number is recorded."""
        mock_launch.return_value = _mock_popen(exit_code=1)

        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            on_failure="retry",
            retry_config=RetryConfig(max_retries=2, backoff_seconds=0.01),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        execute_foreground(rs, step)

        # The last outcome should record the final attempt (0-indexed: 2)
        assert rs.log.steps[-1].attempt == 2

    @patch("swarm.plan.executor.time.sleep")
    @patch("swarm.plan.executor.launch_agent")
    def test_retry_with_on_failure_stop_after_no_retry_config(
        self,
        mock_launch: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        """on_failure='stop' with no retry_config should fail immediately."""
        mock_launch.return_value = _mock_popen(exit_code=1)

        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            on_failure="stop",
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        execute_foreground(rs, step)

        assert "s1" in rs.failed
        assert mock_launch.call_count == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# execute_plan with retry integration
# ---------------------------------------------------------------------------


class TestExecutePlanWithRetry:
    @patch("swarm.plan.executor.time.sleep")
    @patch("swarm.plan.executor.launch_agent")
    @patch("swarm.plan.executor.find_claude_binary")
    def test_retry_step_in_full_plan(
        self,
        mock_find: MagicMock,
        mock_launch: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")

        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _mock_popen(exit_code=1)
            return _mock_popen(exit_code=0)

        mock_launch.side_effect = _side_effect

        step = PlanStep(
            id="s1",
            type="task",
            prompt="do work",
            agent_type="worker",
            on_failure="retry",
            retry_config=RetryConfig(max_retries=3, backoff_seconds=0.01),
        )
        plan = _plan(step)
        rs = _make_run_state(plan, tmp_path)

        result = execute_plan(rs)

        assert result["status"] == "completed"
        assert "s1" in result["completed_step_ids"]
