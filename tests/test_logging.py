"""Tests for swarm.logging: configure_logging (stderr-only)."""

from __future__ import annotations

import logging

from swarm.logging import configure_logging


class TestLoggerConfigures:
    def test_returns_bound_logger(self) -> None:
        log = configure_logging()
        assert log is not None

    def test_stderr_handler_exists(self) -> None:
        configure_logging()
        root = logging.getLogger("swarm")
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types

    def test_no_file_handler(self) -> None:
        configure_logging()
        root = logging.getLogger("swarm")
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "FileHandler" not in handler_types


class TestLogLevelFiltering:
    def test_respects_level_parameter(self) -> None:
        configure_logging(level="WARNING")
        root = logging.getLogger("swarm")
        assert root.level == logging.WARNING
        # Reset
        configure_logging(level="INFO")
