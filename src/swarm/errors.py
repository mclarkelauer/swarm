"""Exception hierarchy for Swarm."""


class SwarmError(Exception):
    """Base exception for all Swarm errors."""


class ConfigError(SwarmError):
    """Raised when configuration is invalid or cannot be loaded."""


class RegistryError(SwarmError):
    """Raised when an agent registry operation fails."""


class ForgeError(SwarmError):
    """Raised when an agent forge operation fails."""


class PlanError(SwarmError):
    """Raised when a plan operation fails."""


class ExecutionError(SwarmError):
    """Raised when a plan execution operation fails."""


class RunLogCorruptError(SwarmError):
    """Raised when a run log file is corrupt and cannot be reconstructed.

    This indicates the on-disk ``run_log.json`` is malformed and neither
    the rolling ``.prev`` backup nor reconstruction from ``events.ndjson``
    yielded a usable log.  Surfacing this loudly avoids the silent
    "treat-as-fresh-run" failure mode that would re-execute completed
    steps.
    """


class SwarmMemoryError(SwarmError):
    """Raised when an agent memory operation fails."""


class MessagingError(SwarmError):
    """Raised when an inter-agent messaging operation fails."""
