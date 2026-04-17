"""Tests for swarm.cli.launch — interactive Claude Code session launcher.

Covers:
    * ``_resolve_mcp_cmd`` binary discovery (venv, PATH, fallback).
    * ``_resolve_claude_cmd`` binary discovery and missing-binary error.
    * ``launch_claude_session``: MCP config construction, env propagation,
      and the ``os.execvp`` invocation.

Notes on what's NOT in launch.py:
    * There is no ``build_mcp_config`` helper — config is built inline.
    * There is no ``CLAUDE_BINARY`` env override — discovery is purely via
      ``shutil.which("claude")``.  Tests assert the actual behavior:
      ``SystemExit(1)`` (raised via Click) when the binary is missing.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.cli import launch
from swarm.config import SwarmConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_config(tmp_path: Path) -> Iterator[SwarmConfig]:
    """Patch ``load_config`` so launch.py uses a temp base_dir.

    Ensures the test never writes to the real ``~/.swarm`` tree.
    """
    base = tmp_path / ".swarm"
    base.mkdir(parents=True, exist_ok=True)
    cfg = SwarmConfig(base_dir=base)
    with patch("swarm.cli.launch.load_config", return_value=cfg):
        yield cfg


# ---------------------------------------------------------------------------
# _resolve_mcp_cmd
# ---------------------------------------------------------------------------


class TestResolveMcpCmd:
    def test_returns_venv_binary_when_present(self, tmp_path: Path) -> None:
        """When a swarm-mcp binary lives next to the python executable, prefer it."""
        fake_venv = tmp_path / "bin"
        fake_venv.mkdir()
        fake_mcp = fake_venv / "swarm-mcp"
        fake_mcp.write_text("#!/bin/sh\nexit 0\n")

        with patch("swarm.cli.launch.sys.executable", str(fake_venv / "python")):
            result = launch._resolve_mcp_cmd()

        assert result == str(fake_mcp)

    def test_falls_back_to_path_lookup(self, tmp_path: Path) -> None:
        """When no venv binary exists, fall back to shutil.which."""
        # Point sys.executable somewhere with no swarm-mcp neighbour.
        fake_python = tmp_path / "no-mcp" / "python"
        fake_python.parent.mkdir()

        with (
            patch("swarm.cli.launch.sys.executable", str(fake_python)),
            patch("swarm.cli.launch.shutil.which", return_value="/usr/local/bin/swarm-mcp"),
        ):
            assert launch._resolve_mcp_cmd() == "/usr/local/bin/swarm-mcp"

    def test_returns_bare_name_when_nothing_found(self, tmp_path: Path) -> None:
        """When no binary is anywhere, return the bare name as a last resort."""
        fake_python = tmp_path / "nowhere" / "python"
        fake_python.parent.mkdir()

        with (
            patch("swarm.cli.launch.sys.executable", str(fake_python)),
            patch("swarm.cli.launch.shutil.which", return_value=None),
        ):
            assert launch._resolve_mcp_cmd() == "swarm-mcp"


# ---------------------------------------------------------------------------
# _resolve_claude_cmd
# ---------------------------------------------------------------------------


class TestResolveClaudeCmd:
    def test_returns_path_when_found(self) -> None:
        with patch("swarm.cli.launch.shutil.which", return_value="/usr/local/bin/claude"):
            assert launch._resolve_claude_cmd() == "/usr/local/bin/claude"

    def test_raises_systemexit_when_missing(self) -> None:
        """Missing claude binary aborts session launch with a clear message."""
        with (
            patch("swarm.cli.launch.shutil.which", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            launch._resolve_claude_cmd()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# launch_claude_session — MCP config construction & env propagation
# ---------------------------------------------------------------------------


class TestLaunchClaudeSessionConfigBuild:
    def test_writes_mcp_config_with_swarm_server_block(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """The written MCP config has an ``mcpServers.swarm`` block whose
        ``command`` points at the resolved swarm-mcp binary."""
        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch(
                "swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp",
            ),
            patch("swarm.cli.launch.os.execvp") as mock_exec,
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(system_prompt="prompt")

        # Verify execvp was called (process replacement is mocked out).
        mock_exec.assert_called_once()

        config_path = isolated_config.base_dir / "run" / "mcp_config.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert "mcpServers" in config
        assert "swarm" in config["mcpServers"]
        assert config["mcpServers"]["swarm"]["command"] == "/fake/swarm-mcp"

    def test_mcp_config_propagates_env_vars(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """SWARM_BASE_DIR and SWARM_PLANS_DIR flow into the server env block."""
        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp"),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(system_prompt="prompt")

        config_path = isolated_config.base_dir / "run" / "mcp_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        env = config["mcpServers"]["swarm"]["env"]

        assert env["SWARM_BASE_DIR"] == str(isolated_config.base_dir)
        # SWARM_PLANS_DIR is set to the cwd at launch time — non-empty path.
        assert env["SWARM_PLANS_DIR"]
        assert Path(env["SWARM_PLANS_DIR"]).is_absolute()

    def test_attaches_mcp_config_to_claude_invocation(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """The argv passed to ``os.execvp`` includes ``--mcp-config <path>`` and
        the path on disk has the right shape."""
        captured: dict[str, list[str]] = {}

        def _capture_exec(binary: str, argv: list[str]) -> None:
            captured["binary"] = [binary]
            captured["argv"] = argv

        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp", side_effect=_capture_exec),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(
                system_prompt="hello world",
                session_name="swarm-orchestrator",
            )

        argv = captured["argv"]
        assert argv[0] == "/fake/claude"
        assert "--dangerously-skip-permissions" in argv
        assert "--mcp-config" in argv
        mcp_idx = argv.index("--mcp-config")
        config_path = Path(argv[mcp_idx + 1])
        assert config_path.exists()
        # Confirm shape (already covered above, but double-check this is the
        # SAME file pointed at from argv).
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert "mcpServers" in config
        assert "swarm" in config["mcpServers"]

    def test_attaches_session_name_when_provided(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        captured: dict[str, list[str]] = {}

        def _capture_exec(binary: str, argv: list[str]) -> None:
            captured["argv"] = argv

        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp", side_effect=_capture_exec),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(
                system_prompt="prompt",
                session_name="swarm-forge",
            )

        argv = captured["argv"]
        assert "--name" in argv
        assert argv[argv.index("--name") + 1] == "swarm-forge"

    def test_no_session_name_omits_name_flag(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        captured: dict[str, list[str]] = {}

        def _capture_exec(binary: str, argv: list[str]) -> None:
            captured["argv"] = argv

        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp", side_effect=_capture_exec),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(system_prompt="prompt", session_name="")

        assert "--name" not in captured["argv"]

    def test_passes_system_prompt_to_claude(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        captured: dict[str, list[str]] = {}

        def _capture_exec(binary: str, argv: list[str]) -> None:
            captured["argv"] = argv

        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp", side_effect=_capture_exec),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(
                system_prompt="my-prompt-payload",
                session_name="",
            )

        argv = captured["argv"]
        assert "--system-prompt" in argv
        assert argv[argv.index("--system-prompt") + 1] == "my-prompt-payload"


# ---------------------------------------------------------------------------
# launch_claude_session — failure modes
# ---------------------------------------------------------------------------


class TestLaunchClaudeSessionFailures:
    def test_falls_back_when_claude_binary_missing(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """Without a discoverable ``claude`` binary, the session aborts loudly."""
        with (
            patch("swarm.cli.launch.shutil.which", return_value=None),
            patch("swarm.cli.launch.seed_base_agents"),
            patch("swarm.cli.launch.os.execvp") as mock_exec,pytest.raises(SystemExit) as exc_info
        ):
            launch.launch_claude_session(system_prompt="prompt")

        assert exc_info.value.code == 1
        # execvp must NOT have been reached.
        mock_exec.assert_not_called()

    def test_seeding_failure_does_not_block_launch(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """If seed_base_agents raises, the session still launches.

        The seeding wrapper inside launch.py is a bare try/except that
        intentionally swallows everything so a corrupt registry can't
        prevent the user from getting a Claude session.
        """
        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch(
                "swarm.cli.launch.seed_base_agents",
                side_effect=RuntimeError("registry broken"),
            ),
            patch("swarm.cli.launch.os.execvp") as mock_exec,
        ):
            launch.launch_claude_session(system_prompt="prompt")

        # Despite the seeding failure, execvp was reached.
        mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# Banner emission
# ---------------------------------------------------------------------------


class TestLaunchBanners:
    def test_known_banner_emitted_for_known_session(
        self,
        isolated_config: SwarmConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp"),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(
                system_prompt="prompt",
                session_name="swarm-orchestrator",
            )

        captured = capsys.readouterr()
        assert "SWARM ORCHESTRATOR" in captured.out

    def test_unknown_session_name_emits_no_banner(
        self,
        isolated_config: SwarmConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp"),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(
                system_prompt="prompt",
                session_name="unknown-session",
            )

        captured = capsys.readouterr()
        # The banner dict has no key for "unknown-session" so nothing prints.
        assert "SWARM ORCHESTRATOR" not in captured.out
        assert "SWARM FORGE" not in captured.out


# ---------------------------------------------------------------------------
# Idempotency: re-launch overwrites the deterministic config path.
# ---------------------------------------------------------------------------


class TestLaunchIdempotency:
    def test_relaunch_overwrites_existing_config(
        self,
        isolated_config: SwarmConfig,
    ) -> None:
        """Re-running launch should refresh the deterministic mcp_config.json."""
        run_dir = isolated_config.base_dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        stale_path = run_dir / "mcp_config.json"
        stale_path.write_text('{"stale": true}', encoding="utf-8")

        with (
            patch("swarm.cli.launch._resolve_claude_cmd", return_value="/fake/claude"),
            patch("swarm.cli.launch._resolve_mcp_cmd", return_value="/fake/swarm-mcp"),
            patch("swarm.cli.launch.os.execvp"),
            patch("swarm.cli.launch.seed_base_agents"),
        ):
            launch.launch_claude_session(system_prompt="prompt")

        config = json.loads(stale_path.read_text(encoding="utf-8"))
        assert "mcpServers" in config
        assert "stale" not in config


# Ensure ``sys`` import is exercised so module imports stay green if the
# launch module's structure changes.
def test_module_exposes_expected_attributes() -> None:
    assert hasattr(launch, "_resolve_mcp_cmd")
    assert hasattr(launch, "_resolve_claude_cmd")
    assert hasattr(launch, "launch_claude_session")
    assert sys.executable  # smoke check
