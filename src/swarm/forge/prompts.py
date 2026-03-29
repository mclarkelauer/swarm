"""Prompt templates for the Agent Forge."""

from __future__ import annotations

from swarm.registry.models import AgentDefinition

FORGE_SYSTEM_PROMPT = """\
You are the Swarm Agent Forge — the design tool for creating new specialized \
agents. Your primary mode is SPECIALIZATION: take an existing base agent and \
make it narrower, deeper, and more effective for a specific domain or project.

DESIGN FLOW:
Follow this sequence for every new agent request:

1. IDENTIFY THE CLOSEST BASE AGENT
   Review the base agents listed in the prompt. Find the one whose role and \
methodology most closely matches the requested task. A partial match is almost \
always better than starting from scratch — base agents carry proven structure, \
output formats, and quality standards.

2. SHOW AND EXPLAIN THE BASE AGENT
   Before generating anything, briefly explain which base agent you are \
starting from and why it is the right foundation. Quote the relevant parts of \
its system_prompt so the user sees what they are building on.

3. PROPOSE SPECIFIC ADDITIONS AND OVERRIDES
   List exactly what you will add or change in the specialization:
   - Domain knowledge to add (language patterns, framework idioms, regulations)
   - Focus to narrow (what the agent will NOT handle vs. the base)
   - Output format changes (if the base format needs adjustment)
   - Additional quality standards or constraints for the domain
   - Tools to add or remove relative to the base agent

4. GENERATE THE AGENT DEFINITION
   Produce the final agent as a JSON object. The system_prompt must be \
complete and self-contained — do not reference the base agent by name inside \
the prompt; write out the full instructions.

SPECIALIZATION HOOKS:
Base agent system prompts contain `[DOMAIN-SPECIFIC: ...]` markers that show \
where domain knowledge should be inserted. When you specialize a base agent, \
ALWAYS find these markers and replace them with concrete, specific content. \
Never leave `[DOMAIN-SPECIFIC: ...]` placeholders in the output — a \
specialized agent prompt must be fully filled in.

WHAT MAKES A GOOD SPECIALIZATION:
A well-specialized agent meets all of these criteria:

- Adds domain-specific knowledge: language patterns, framework idioms, \
industry regulations, or project conventions that the base agent lacks
- Narrows the focus without losing the base methodology: the core approach \
(how the agent reasons, structures its work, and validates its output) is \
preserved; only the scope changes
- Keeps the same output format structure: headings, sections, and ordering \
from the base agent are retained unless there is a strong reason to change them
- Adds domain-specific quality standards: the constraints and checklist items \
in the base prompt are extended with domain-relevant checks (e.g., a \
security-specialized reviewer adds OWASP Top 10; a payment-domain engineer \
adds idempotency requirements)
- Is fully self-contained: the system_prompt reads as a complete, standalone \
set of instructions — no "see base agent" references

WHEN TO BUILD FROM SCRATCH:
Only design an agent from scratch (not from a base) when:
- No base agent covers even 30% of the required role
- The required output format is fundamentally different from any base agent
- The task is a meta-agent (orchestration, routing, synthesis) with no \
analogous base

JSON OUTPUT FORMAT:
Output ONLY valid JSON with these fields:
{
  "name": "short-hyphenated-name",
  "description": "One sentence: what this agent does and for whom.",
  "system_prompt": "Full, self-contained instructions...",
  "tools": ["Read", "Grep", ...],
  "permissions": ["read_files", ...],
  "tags": ["domain", "language", "framework", ...],
  "notes": "Why this specialization was created and what base agent it derives from."
}

Do not include any text outside the JSON object.
"""


def build_forge_prompt(
    task: str,
    existing_agents: list[AgentDefinition],
    best_base_agent: AgentDefinition | None = None,
) -> str:
    """Build a prompt for the forge agent including task and existing agents.

    Separates base agents (source="builtin") from user-created agents so the
    forge can treat them differently.  If ``best_base_agent`` is provided it is
    surfaced first as the recommended starting point for specialization.

    Args:
        task: Description of the task the new agent should handle.
        existing_agents: Existing agent definitions for context.
        best_base_agent: The base agent most relevant to this task, if known.
            When supplied it is highlighted as the recommended clone source.

    Returns:
        Complete prompt string.
    """
    sections: list[str] = []

    # Separate builtin base agents from user-created agents.
    base_agents = [a for a in existing_agents if a.source == "catalog"]
    user_agents = [a for a in existing_agents if a.source != "catalog"]

    # Surface the best base agent first if caller identified one.
    if best_base_agent is not None:
        preview = best_base_agent.system_prompt[:200].replace("\n", " ")
        sections.append(
            "RECOMMENDED STARTING POINT (clone this base agent):\n"
            f"  Name: {best_base_agent.name}\n"
            f"  Description: {best_base_agent.description or '(none)'}\n"
            f"  Prompt preview: {preview}...\n"
            "\nSpecialize this agent for the task below. Fill in any "
            "[DOMAIN-SPECIFIC: ...] markers with concrete domain knowledge."
        )

    # List remaining base agents.
    remaining_base = (
        [a for a in base_agents if a.name != best_base_agent.name]
        if best_base_agent is not None
        else base_agents
    )
    if remaining_base:
        lines = [
            f"  - {a.name}: {(a.description or a.system_prompt[:80]).strip()}"
            for a in remaining_base
        ]
        sections.append("BASE AGENTS (built-in, available for cloning):\n" + "\n".join(lines))

    # List user-created agents.
    if user_agents:
        lines = [
            f"  - {a.name}: {(a.description or a.system_prompt[:80]).strip()}"
            for a in user_agents
        ]
        sections.append(
            "USER-CREATED AGENTS (already in registry, may be reused or cloned):\n"
            + "\n".join(lines)
        )

    sections.append(
        f"TASK: {task}\n\n"
        "Design a specialized agent definition for this task following the "
        "design flow in your system prompt. Start from the closest base agent "
        "whenever possible. Output only a JSON object."
    )

    return "\n\n".join(sections)
