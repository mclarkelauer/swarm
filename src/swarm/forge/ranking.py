"""Semantic re-ranking support for agent suggestion."""

from __future__ import annotations

import re

from swarm.registry.models import AgentDefinition


def build_ranking_prompt(query: str, candidates: list[AgentDefinition]) -> str:
    """Produce prompt asking LLM to rank candidates by relevance.

    Args:
        query: The task description to rank against.
        candidates: List of agent definitions to rank.

    Returns:
        A prompt string that asks the LLM to return a comma-separated list of
        candidate numbers ordered from most to least relevant.
    """
    lines: list[str] = [
        "You are ranking agent definitions by relevance to a task.",
        "",
        f"Task: {query}",
        "",
        "Candidates:",
    ]
    for i, agent in enumerate(candidates, start=1):
        desc = agent.description if agent.description else "(no description)"
        lines.append(f"  {i}. {agent.name} — {desc}")
    lines += [
        "",
        "Rank these candidates from most relevant to least relevant.",
        "Return ONLY a comma-separated list of the candidate numbers",
        "in order of relevance (e.g. '3, 1, 2').",
    ]
    return "\n".join(lines)


def parse_ranking_response(
    response: str, candidates: list[AgentDefinition]
) -> list[AgentDefinition]:
    """Parse LLM ranking response and reorder candidates.

    Parsing strategy:
    1. Extract numbers via ``re.findall(r"\\d+", response)``, map to 1-based
       candidate indices.  Numbers out of range are ignored.
    2. Fallback: try matching agent names line by line.
    3. Final fallback: return original order.
    4. Unmentioned candidates are always appended at the end.

    Args:
        response: The raw text response from the LLM.
        candidates: The original ordered list of candidates.

    Returns:
        A reordered list of all candidates, from most to least relevant.
    """
    if not candidates:
        return []

    # --- Strategy 1: numeric ranking ---
    raw_numbers = re.findall(r"\d+", response)
    if raw_numbers:
        seen: set[int] = set()
        ranked: list[AgentDefinition] = []
        for token in raw_numbers:
            idx = int(token) - 1  # convert 1-based to 0-based
            if 0 <= idx < len(candidates) and idx not in seen:
                seen.add(idx)
                ranked.append(candidates[idx])
        if ranked:
            # Append any unmentioned candidates in their original order
            for i, agent in enumerate(candidates):
                if i not in seen:
                    ranked.append(agent)
            return ranked

    # --- Strategy 2: name matching line by line ---
    name_to_agent: dict[str, AgentDefinition] = {a.name: a for a in candidates}
    seen_names: set[str] = set()
    name_ranked: list[AgentDefinition] = []
    for line in response.splitlines():
        line = line.strip()
        if line in name_to_agent and line not in seen_names:
            seen_names.add(line)
            name_ranked.append(name_to_agent[line])
    if name_ranked:
        for agent in candidates:
            if agent.name not in seen_names:
                name_ranked.append(agent)
        return name_ranked

    # --- Strategy 3: original order ---
    return list(candidates)
