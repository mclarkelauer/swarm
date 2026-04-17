"""High-level API for the Agent Forge."""

from __future__ import annotations

from pathlib import Path

from swarm.forge.cache import read_cache, write_cache
from swarm.registry.api import RegistryAPI
from swarm.registry.models import AgentDefinition
from swarm.registry.sources import SourcePlugin


class ForgeAPI:
    """Create, clone, and suggest agents via the forge.

    Args:
        registry_db: Path to the registry SQLite database.
        cache_dir: Path to the forge disk cache directory.
        sources: Optional list of :class:`SourcePlugin` instances to query
            when suggesting agents.  The registry is always searched first,
            then each source in order.  Duplicates (by ``id``) are removed.
    """

    def __init__(
        self,
        registry_db: Path,
        cache_dir: Path,
        sources: list[SourcePlugin] | None = None,
    ) -> None:
        self._registry = RegistryAPI(registry_db)
        self._cache_dir = cache_dir
        self._sources: list[SourcePlugin] = sources or []

    def create_agent(
        self,
        name: str,
        system_prompt: str,
        tools: list[str],
        permissions: list[str],
        description: str = "",
        tags: list[str] | None = None,
        notes: str = "",
    ) -> AgentDefinition:
        """Create and register a new agent definition.

        Also writes it to the disk cache.
        """
        defn = self._registry.create(
            name=name,
            system_prompt=system_prompt,
            tools=tools,
            permissions=permissions,
            source="forge",
            description=description,
            tags=tags,
            notes=notes,
        )
        write_cache(self._cache_dir, defn)
        return defn

    def clone_agent(
        self, source_id: str, overrides: dict[str, str | int | list[str]]
    ) -> AgentDefinition:
        """Clone an existing agent with overrides. Maintains provenance."""
        defn = self._registry.clone(source_id, overrides)
        write_cache(self._cache_dir, defn)
        return defn

    def suggest_agent(self, task_description: str) -> list[AgentDefinition]:
        """Suggest existing agents that match a task description.

        Searches the registry first, then every registered source plugin in
        order.  Results are deduplicated by ``id`` (first occurrence wins).
        """
        results = self._registry.search(task_description)
        for source in self._sources:
            results.extend(source.search(task_description))
        # Deduplicate by id, preserving order (registry hits first)
        seen: set[str] = set()
        unique: list[AgentDefinition] = []
        for defn in results:
            if defn.id not in seen:
                seen.add(defn.id)
                unique.append(defn)
        return unique

    def get_cached(self, name: str) -> AgentDefinition | None:
        """Check disk cache first, then fall back to registry."""
        cached = read_cache(self._cache_dir, name)
        if cached is not None:
            return cached
        results = self._registry.list_agents(name_filter=name)
        return results[0] if results else None

    def close(self) -> None:
        """Close the underlying registry connection."""
        self._registry.close()

    def __enter__(self) -> ForgeAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
