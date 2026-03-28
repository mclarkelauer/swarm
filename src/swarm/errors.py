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
