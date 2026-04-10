"""MCP tools for the inter-agent message bus."""

from __future__ import annotations

import json
from pathlib import Path

from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.messaging.api import MessageAPI


def _get_message_api() -> MessageAPI:
    """Resolve the MessageAPI, creating it lazily from the plans directory."""
    if state.message_api is not None:
        return state.message_api
    plans_dir = Path(state.plans_dir) if state.plans_dir else Path.cwd()
    db_path = plans_dir / "messages.db"
    return MessageAPI(db_path)


@mcp.tool()
def agent_send_message(
    from_agent: str,
    to_agent: str,
    content: str,
    step_id: str = "",
    run_id: str = "",
    message_type: str = "response",
) -> str:
    """Send a message from one agent to another within a plan run.

    Args:
        from_agent: Agent type of the sender.
        to_agent: Agent type of the receiver. Use '*' for broadcast.
        content: Message content (freeform text or JSON string).
        step_id: Optional step ID that produced this message.
        run_id: Plan run identifier (from the run log).
        message_type: One of 'request', 'response', 'broadcast'.

    Returns:
        JSON ``{"ok": true, "message": {...}}`` with the persisted message,
        or ``{"error": "..."}`` on validation failure.
    """
    if message_type not in ("request", "response", "broadcast"):
        return json.dumps({
            "error": (
                f"Invalid message_type '{message_type}'; "
                f"must be 'request', 'response', or 'broadcast'"
            ),
        })

    if not from_agent:
        return json.dumps({"error": "from_agent is required"})
    if not to_agent:
        return json.dumps({"error": "to_agent is required"})

    api = _get_message_api()
    msg = api.send(
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        message_type=message_type,
        step_id=step_id,
        run_id=run_id,
    )
    return json.dumps({"ok": True, "message": msg.to_dict()})


@mcp.tool()
def agent_receive_messages(
    agent_name: str,
    run_id: str,
    since: str = "",
    limit: str = "50",
) -> str:
    """Retrieve messages addressed to a specific agent in a plan run.

    Includes both direct messages and broadcasts (to_agent='*').

    Args:
        agent_name: Agent type to receive messages for.
        run_id: Plan run identifier.
        since: Optional ISO timestamp; only return messages created after
            this time.
        limit: Maximum number of messages to return (default '50').

    Returns:
        JSON array of message objects, newest first.
    """
    try:
        max_messages = int(limit)
    except ValueError:
        return json.dumps({"error": f"Invalid limit: {limit!r}"})

    api = _get_message_api()
    messages = api.receive(
        agent_name=agent_name,
        run_id=run_id,
        since=since,
        limit=max_messages,
    )
    return json.dumps([m.to_dict() for m in messages])


@mcp.tool()
def agent_broadcast(
    from_agent: str,
    content: str,
    step_id: str = "",
    run_id: str = "",
) -> str:
    """Broadcast a message to all agents in a plan run.

    Shorthand for ``agent_send_message`` with ``to_agent='*'`` and
    ``message_type='broadcast'``.

    Args:
        from_agent: Agent type of the sender.
        content: Message content.
        step_id: Optional step ID that produced this message.
        run_id: Plan run identifier.

    Returns:
        JSON ``{"ok": true, "message": {...}}`` with the persisted message.
    """
    if not from_agent:
        return json.dumps({"error": "from_agent is required"})

    api = _get_message_api()
    msg = api.broadcast(
        from_agent=from_agent,
        content=content,
        step_id=step_id,
        run_id=run_id,
    )
    return json.dumps({"ok": True, "message": msg.to_dict()})


@mcp.tool()
def agent_reply_message(
    original_message_id: str,
    from_agent: str,
    content: str,
    run_id: str = "",
) -> str:
    """Reply to a message, automatically setting correlation ID.

    Args:
        original_message_id: ID of the message being replied to.
        from_agent: Name of the replying agent.
        content: Reply content.
        run_id: Plan run identifier.

    Returns:
        JSON object with the reply message.
    """
    api = _get_message_api()
    msg = api.reply(
        original_message_id, from_agent, content, run_id=run_id,
    )
    return json.dumps(msg.to_dict())


@mcp.tool()
def agent_acknowledge_message(message_id: str) -> str:
    """Mark a message as read/acknowledged.

    Args:
        message_id: The message UUID to acknowledge.

    Returns:
        JSON object: {"ok": true/false, "message_id": "..."}.
    """
    api = _get_message_api()
    acked = api.acknowledge(message_id)
    return json.dumps({"ok": acked, "message_id": message_id})
