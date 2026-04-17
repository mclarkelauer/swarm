"""Tests for swarm.mcp.server: main entry point."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.dirs import ensure_base_dir


@pytest.fixture(autouse=True)
def _close_state_apis() -> Iterator[None]:
    """Close any state APIs that ``main()`` populates so the underlying
    SQLite connections do not leak across tests."""
    from swarm.mcp import state

    yield
    for attr in ("registry_api", "forge_api", "memory_api", "message_api", "context_api"):
        api = getattr(state, attr, None)
        if api is not None:
            with __import__("contextlib").suppress(Exception):
                api.close()
            setattr(state, attr, None)


class TestMcpServerMain:
    def test_defaults_base_dir_to_home_throng(self, tmp_path: Path) -> None:
        from swarm.mcp import state
        from swarm.mcp.server import main

        base_dir = tmp_path / ".swarm"
        ensure_base_dir(base_dir)

        with (
            patch.dict(
                "os.environ",
                {"SWARM_BASE_DIR": str(base_dir)},
                clear=True,
            ),
            patch("swarm.mcp.server.mcp") as mock_mcp,
        ):
            main()
            assert state.registry_api is not None
            assert state.forge_api is not None
            assert state.plans_dir  # non-empty string
            mock_mcp.run.assert_called_once()

    def test_uses_throng_plans_dir_env(self, tmp_path: Path) -> None:
        from swarm.mcp import state
        from swarm.mcp.server import main

        base_dir = tmp_path / ".swarm"
        ensure_base_dir(base_dir)
        plans = tmp_path / "myplans"
        plans.mkdir()

        with (
            patch.dict(
                "os.environ",
                {"SWARM_BASE_DIR": str(base_dir), "SWARM_PLANS_DIR": str(plans)},
                clear=True,
            ),
            patch("swarm.mcp.server.mcp") as mock_mcp,
        ):
            main()
            assert state.plans_dir == str(plans)
            mock_mcp.run.assert_called_once()
