"""Inter-agent message bus -- lightweight typed messaging between agents."""

from __future__ import annotations

from swarm.messaging.api import MessageAPI
from swarm.messaging.models import AgentMessage

__all__ = [
    "AgentMessage",
    "MessageAPI",
]
