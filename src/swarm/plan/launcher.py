"""Agent subprocess management for plan execution.

Handles launching ``claude`` CLI subprocesses for agent invocations,
locating the Claude binary, and waiting with timeout support.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

import structlog

from swarm.errors import ExecutionError

logger = structlog.get_logger()

_SIGTERM_GRACE_SECONDS = 10


def find_claude_binary() -> Path:
    """Locate the ``claude`` CLI binary on the system PATH.

    Returns:
        Absolute path to the ``claude`` executable.

    Raises:
        ExecutionError: If the binary cannot be found.
    """
    binary = shutil.which("claude")
    if binary is None:
        raise ExecutionError(
            "The 'claude' CLI binary was not found on PATH. "
            "Install it from https://docs.anthropic.com/claude-code "
            "and ensure it is available in your shell."
        )
    return Path(binary).resolve()


def wait_with_timeout(proc: subprocess.Popen[str], timeout: int | None) -> int:
    """Wait for *proc* to finish, enforcing an optional timeout.

    On timeout the process receives SIGTERM followed by SIGKILL after a
    grace period.

    Args:
        proc: The subprocess to wait on.
        timeout: Maximum seconds to wait.  ``None`` means wait forever.

    Returns:
        The process exit code.
    """
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(
            "agent_timeout",
            pid=proc.pid,
            timeout=timeout,
        )
        proc.send_signal(signal.SIGTERM)
        try:
            return proc.wait(timeout=_SIGTERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("agent_sigkill", pid=proc.pid)
            proc.kill()
            return proc.wait()


def launch_agent(
    agent_prompt: str,
    step_prompt: str,
    tools: list[str],
    artifacts_dir: Path,
    step_id: str,
    env_extras: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.Popen[str]:
    """Launch a ``claude`` CLI subprocess for an agent invocation.

    Passes the agent system prompt via ``--system-prompt`` and invokes
    the ``claude`` binary in print mode (``-p``).

    Args:
        agent_prompt: The agent's full system prompt text.
        step_prompt: The interpolated prompt for this specific step.
        tools: List of tool names the agent is allowed to use.
        artifacts_dir: Directory for step output artifacts and logs.
        step_id: Unique identifier for this step (used in log file names
            and environment variables).
        env_extras: Additional environment variables to set for the
            subprocess.
        timeout: Per-step timeout in seconds (passed through but not
            enforced here -- callers use :func:`wait_with_timeout`).

    Returns:
        The :class:`subprocess.Popen` handle.  For foreground execution
        the caller should call :func:`wait_with_timeout`.  For background
        execution the handle is stored in ``RunState.background_procs``.

    Raises:
        ExecutionError: If the ``claude`` binary cannot be found.
    """
    claude_bin = find_claude_binary()

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Build command.  ``--output-format json`` makes the CLI emit a single
    # machine-readable result object on stdout (with ``total_cost_usd``,
    # ``usage``, ``modelUsage`` keys) so the executor can record cost data
    # deterministically instead of regex-scraping arbitrary stderr lines.
    cmd: list[str] = [
        str(claude_bin),
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
        "--system-prompt",
        agent_prompt,
        "-p",
        step_prompt,
    ]

    if tools:
        cmd.extend(["--allowedTools", ",".join(tools)])

    # Build environment
    env = os.environ.copy()
    env["SWARM_STEP_ID"] = step_id
    env["SWARM_ARTIFACTS_DIR"] = str(artifacts_dir)
    if env_extras:
        env.update(env_extras)

    # Open log files
    stdout_path = artifacts_dir / f"{step_id}.stdout.log"
    stderr_path = artifacts_dir / f"{step_id}.stderr.log"
    stdout_fh = stdout_path.open("w")
    stderr_fh = stderr_path.open("w")

    logger.info(
        "launch_agent",
        step_id=step_id,
        claude_bin=str(claude_bin),
    )

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
            env=env,
        )
    except OSError as exc:
        stdout_fh.close()
        stderr_fh.close()
        raise ExecutionError(
            f"Failed to launch claude subprocess for step '{step_id}': {exc}"
        ) from exc

    # Popen dups the file descriptors, so closing the Python file objects
    # is safe and prevents FD leaks.
    stdout_fh.close()
    stderr_fh.close()

    logger.info("agent_started", step_id=step_id, pid=proc.pid)
    return proc
