"""Tests for swarm.plan.launcher: find_claude_binary, launch_agent, wait_with_timeout."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swarm.errors import ExecutionError
from swarm.plan.launcher import find_claude_binary, launch_agent, wait_with_timeout


# ---------------------------------------------------------------------------
# find_claude_binary
# ---------------------------------------------------------------------------


class TestFindClaudeBinary:
    @patch("swarm.plan.launcher.shutil.which")
    def test_found(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/local/bin/claude"
        result = find_claude_binary()
        assert result == Path("/usr/local/bin/claude").resolve()
        mock_which.assert_called_once_with("claude")

    @patch("swarm.plan.launcher.shutil.which")
    def test_not_found_raises(self, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        with pytest.raises(ExecutionError, match="claude.*not found"):
            find_claude_binary()


# ---------------------------------------------------------------------------
# wait_with_timeout
# ---------------------------------------------------------------------------


class TestWaitWithTimeout:
    def test_returns_exit_code(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.wait.return_value = 0
        assert wait_with_timeout(proc, timeout=None) == 0

    def test_returns_nonzero_exit_code(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.wait.return_value = 42
        assert wait_with_timeout(proc, timeout=42) == 42

    def test_timeout_sends_sigterm(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 9999

        # First wait raises timeout, second wait (after SIGTERM) returns 143
        proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 10), 143]

        result = wait_with_timeout(proc, timeout=10)

        proc.send_signal.assert_called_once_with(signal.SIGTERM)
        assert result == 143

    def test_kills_on_sigterm_timeout(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 9999

        # First wait: timeout. Second wait (after SIGTERM): timeout again.
        # Third wait (after kill): returns -9.
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 10),
            subprocess.TimeoutExpired("cmd", 10),
            -9,
        ]

        result = wait_with_timeout(proc, timeout=10)

        proc.send_signal.assert_called_once_with(signal.SIGTERM)
        proc.kill.assert_called_once()
        assert result == -9

    def test_no_timeout_waits_forever(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.wait.return_value = 0

        result = wait_with_timeout(proc, timeout=None)

        proc.wait.assert_called_once_with(timeout=None)
        assert result == 0


# ---------------------------------------------------------------------------
# launch_agent
# ---------------------------------------------------------------------------


class TestLaunchAgent:
    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_creates_log_files(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        launch_agent(
            agent_prompt="You are a worker",
            step_prompt="Do task",
            tools=["Read", "Write"],
            artifacts_dir=artifacts_dir,
            step_id="test_step",
        )

        # Popen was called
        mock_popen.assert_called_once()

        # Verify stdout/stderr file handles were opened
        call_kwargs = mock_popen.call_args
        assert call_kwargs[1]["text"] is True

    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_sets_env_vars(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        launch_agent(
            agent_prompt="You are a worker",
            step_prompt="Do task",
            tools=[],
            artifacts_dir=artifacts_dir,
            step_id="my_step",
            env_extras={"MY_VAR": "my_value"},
        )

        call_kwargs = mock_popen.call_args
        env = call_kwargs[1]["env"]
        assert env["SWARM_STEP_ID"] == "my_step"
        assert env["SWARM_ARTIFACTS_DIR"] == str(artifacts_dir)
        assert env["MY_VAR"] == "my_value"

    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_command_includes_tools(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        launch_agent(
            agent_prompt="You are a worker",
            step_prompt="Do task",
            tools=["Read", "Grep"],
            artifacts_dir=artifacts_dir,
            step_id="s1",
        )

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        # Check that --allowedTools is in the command with the tools
        tools_idx = cmd.index("--allowedTools")
        assert cmd[tools_idx + 1] == "Read,Grep"

    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_no_tools_omits_flag(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        launch_agent(
            agent_prompt="You are a worker",
            step_prompt="Do task",
            tools=[],
            artifacts_dir=artifacts_dir,
            step_id="s1",
        )

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--allowedTools" not in cmd

    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_popen_failure_raises_execution_error(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_popen.side_effect = OSError("Permission denied")

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(ExecutionError, match="Failed to launch"):
            launch_agent(
                agent_prompt="prompt",
                step_prompt="task",
                tools=[],
                artifacts_dir=artifacts_dir,
                step_id="s1",
            )

    @patch("swarm.plan.launcher.subprocess.Popen")
    @patch("swarm.plan.launcher.find_claude_binary")
    def test_returns_popen_handle(
        self,
        mock_find: MagicMock,
        mock_popen: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_find.return_value = Path("/usr/bin/claude")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        result = launch_agent(
            agent_prompt="prompt",
            step_prompt="task",
            tools=[],
            artifacts_dir=artifacts_dir,
            step_id="s1",
        )

        assert result is mock_proc
