"""Prompt templates for the Agent Forge."""

from __future__ import annotations

from swarm.registry.models import AgentDefinition

FORGE_SYSTEM_PROMPT = """\
You are the Swarm Agent Forge. Your job is to design new agent definitions.

Given a task description and a list of existing agents, you must output a JSON
agent definition with the following fields:
- name: a short, descriptive agent type name
- system_prompt: detailed instructions for the agent
- tools: list of tools the agent needs
- permissions: list of permissions the agent needs

Output ONLY valid JSON. Do not include any other text.
"""


def build_forge_prompt(
    task: str, existing_agents: list[AgentDefinition]
) -> str:
    """Build a prompt for the forge agent including task and existing agents.

    Args:
        task: Description of the task the new agent should handle.
        existing_agents: Existing agent definitions for context.

    Returns:
        Complete prompt string.
    """
    agent_list = ""
    if existing_agents:
        lines = [f"- {a.name}: {a.system_prompt[:80]}" for a in existing_agents]
        agent_list = "Existing agents:\n" + "\n".join(lines) + "\n\n"

    return (
        f"{agent_list}"
        f"Task: {task}\n\n"
        f"Design a new agent definition for this task. "
        f"Consider reusing or cloning an existing agent if one is similar."
    )
