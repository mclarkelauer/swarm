"""Source plugins for discovering and installing agent definitions.

A source plugin lets the forge query external catalogs of agent definitions —
local directories, Git repos, HTTP APIs, curated bundles, etc.  Every plugin
implements the :class:`SourcePlugin` abstract base class.

Quick-start for writing a new plugin
-------------------------------------

1. Create a new file in ``swarm/registry/sources/`` (e.g. ``github.py``).
2. Subclass :class:`SourcePlugin` and implement the three required methods.
3. Pass an instance of your plugin to :class:`~swarm.forge.api.ForgeAPI`.

Minimal example::

    from pathlib import Path
    from swarm.registry.models import AgentDefinition
    from swarm.registry.sources import SourcePlugin

    class MyCustomSource(SourcePlugin):
        \"\"\"One-line description of what this source provides.\"\"\"

        @property
        def name(self) -> str:
            return "my-source"

        def search(self, query: str) -> list[AgentDefinition]:
            # Return definitions whose name/prompt match *query*.
            # Return an empty list on no match — never raise.
            ...

        def install(self, name: str) -> AgentDefinition:
            # Return the single definition identified by *name*.
            # Raise ``RegistryError`` if not found or invalid.
            ...

Usage::

    from swarm.forge.api import ForgeAPI

    forge = ForgeAPI(
        registry_db=Path("~/.swarm/registry.db"),
        cache_dir=Path("~/.swarm/forge"),
        sources=[MyCustomSource(), LocalDirectorySource(some_dir)],
    )

    # suggest_agent now queries the registry AND every source plugin:
    matches = forge.suggest_agent("code review")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from swarm.registry.models import AgentDefinition


class SourcePlugin(ABC):
    """Abstract base class for agent-definition source plugins.

    A source plugin exposes a read-only catalog of :class:`AgentDefinition`
    objects.  The forge queries every registered plugin when the user asks for
    agent suggestions (via :meth:`~swarm.forge.api.ForgeAPI.suggest_agent`).

    **Contract**

    * ``name`` — unique, short, kebab-case identifier (e.g. ``"local"``,
      ``"github"``, ``"my-api"``).  Used in logging and error messages.
    * ``search`` — fuzzy/substring lookup.  Must never raise; return ``[]``
      when the catalog is empty or the query has no matches.
    * ``install`` — exact lookup by name.  Raise
      :class:`~swarm.errors.RegistryError` when the definition cannot be
      found or is invalid.

    **Thread safety**

    Source plugins may be called from multiple threads.  Keep instance state
    minimal or protect it with a lock if needed.
    """

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this source (e.g. ``"local"``, ``"github"``)."""

    @abstractmethod
    def search(self, query: str) -> list[AgentDefinition]:
        """Return definitions whose name or prompt matches *query*.

        Args:
            query: Free-text search string.  Plugins decide their own
                matching strategy (substring, fuzzy, keyword, etc.).

        Returns:
            A (possibly empty) list of matching definitions.  Ordering is
            up to the plugin — best-match-first is recommended.

        Note:
            Must **never** raise.  If the underlying catalog is unreachable
            or corrupt, return ``[]`` and log the error.
        """

    @abstractmethod
    def install(self, name: str) -> AgentDefinition:
        """Load a single definition by exact *name*.

        Args:
            name: Exact agent name (not ID) to retrieve.

        Returns:
            The matching :class:`AgentDefinition`.

        Raises:
            swarm.errors.RegistryError: If the definition does not exist
                or cannot be deserialized.
        """
