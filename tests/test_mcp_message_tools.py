"""Tests for swarm.mcp.message_tools: agent_send_message, agent_receive_messages, agent_broadcast."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.mcp.message_tools import (
    agent_acknowledge_message,
    agent_broadcast,
    agent_receive_messages,
    agent_reply_message,
    agent_send_message,
)
from swarm.messaging.api import MessageAPI


@pytest.fixture(autouse=True)
def _setup_state(tmp_path: Path) -> Iterator[None]:
    state.message_api = MessageAPI(tmp_path / "messages.db")
    state.plans_dir = str(tmp_path)
    try:
        yield
    finally:
        assert state.message_api is not None
        state.message_api.close()
        state.message_api = None


class TestAgentSendMessage:
    def test_sends_and_returns_message(self) -> None:
        result = json.loads(
            agent_send_message("sender", "receiver", "hello", run_id="r1")
        )
        assert result["ok"] is True
        msg = result["message"]
        assert msg["from_agent"] == "sender"
        assert msg["to_agent"] == "receiver"
        assert msg["content"] == "hello"
        assert "id" in msg

    def test_with_step_id_and_run_id(self) -> None:
        result = json.loads(
            agent_send_message(
                "sender", "receiver", "data",
                step_id="s1", run_id="r1", message_type="request",
            )
        )
        assert result["ok"] is True
        msg = result["message"]
        assert msg["step_id"] == "s1"
        assert msg["run_id"] == "r1"
        assert msg["message_type"] == "request"

    def test_invalid_message_type(self) -> None:
        result = json.loads(
            agent_send_message("a", "b", "c", message_type="invalid")
        )
        assert "error" in result
        assert "invalid" in result["error"].lower() or "Invalid" in result["error"]

    def test_empty_from_agent(self) -> None:
        result = json.loads(agent_send_message("", "b", "c"))
        assert "error" in result
        assert "from_agent" in result["error"]

    def test_empty_to_agent(self) -> None:
        result = json.loads(agent_send_message("a", "", "c"))
        assert "error" in result
        assert "to_agent" in result["error"]

    def test_default_message_type_is_response(self) -> None:
        result = json.loads(agent_send_message("a", "b", "c", run_id="r1"))
        # Sparse serialization: "response" is default, so omitted from dict
        assert result["ok"] is True
        assert result["message"].get("message_type", "response") == "response"


class TestAgentReceiveMessages:
    def test_receives_sent_messages(self) -> None:
        agent_send_message("sender", "receiver", "hello", run_id="r1")
        result = json.loads(agent_receive_messages("receiver", "r1"))
        assert len(result) == 1
        assert result[0]["from_agent"] == "sender"
        assert result[0]["content"] == "hello"

    def test_receives_broadcasts(self) -> None:
        agent_broadcast("sender", "broadcast-msg", run_id="r1")
        result = json.loads(agent_receive_messages("any-agent", "r1"))
        assert len(result) == 1
        assert result[0]["content"] == "broadcast-msg"

    def test_filters_by_run_id(self) -> None:
        agent_send_message("a", "b", "run1", run_id="r1")
        agent_send_message("a", "b", "run2", run_id="r2")
        result = json.loads(agent_receive_messages("b", "r1"))
        assert len(result) == 1
        assert result[0]["content"] == "run1"

    def test_respects_limit(self) -> None:
        for i in range(10):
            agent_send_message("a", "b", f"msg-{i}", run_id="r1")
        result = json.loads(agent_receive_messages("b", "r1", limit="3"))
        assert len(result) == 3

    def test_invalid_limit(self) -> None:
        result = json.loads(agent_receive_messages("a", "r1", limit="not-a-number"))
        assert "error" in result

    def test_empty_result(self) -> None:
        result = json.loads(agent_receive_messages("nobody", "r1"))
        assert result == []


class TestAgentBroadcast:
    def test_broadcasts_message(self) -> None:
        result = json.loads(agent_broadcast("sender", "alert!", run_id="r1"))
        assert result["ok"] is True
        msg = result["message"]
        assert msg["to_agent"] == "*"
        assert msg["message_type"] == "broadcast"
        assert msg["content"] == "alert!"

    def test_broadcast_with_step_id(self) -> None:
        result = json.loads(
            agent_broadcast("sender", "data", step_id="s1", run_id="r1")
        )
        assert result["ok"] is True
        assert result["message"]["step_id"] == "s1"

    def test_broadcast_empty_from_agent(self) -> None:
        result = json.loads(agent_broadcast("", "content"))
        assert "error" in result
        assert "from_agent" in result["error"]

    def test_broadcast_visible_to_multiple_receivers(self) -> None:
        agent_broadcast("sender", "for everyone", run_id="r1")
        r1 = json.loads(agent_receive_messages("agent-a", "r1"))
        r2 = json.loads(agent_receive_messages("agent-b", "r1"))
        assert len(r1) == 1
        assert len(r2) == 1


class TestAgentReplyMessage:
    def test_agent_reply_message_tool(self) -> None:
        # Send an original message
        send_result = json.loads(
            agent_send_message("alice", "bob", "question?", run_id="r1",
                               message_type="request")
        )
        original_id = send_result["message"]["id"]

        # Reply to it
        reply_result = json.loads(
            agent_reply_message(original_id, "bob", "answer!", run_id="r1")
        )
        assert reply_result["from_agent"] == "bob"
        assert reply_result["to_agent"] == "alice"
        assert reply_result["content"] == "answer!"
        assert reply_result["in_reply_to"] == original_id

    def test_reply_sets_response_type(self) -> None:
        send_result = json.loads(
            agent_send_message("alice", "bob", "ping", run_id="r1")
        )
        original_id = send_result["message"]["id"]
        reply_result = json.loads(
            agent_reply_message(original_id, "bob", "pong", run_id="r1")
        )
        # "response" is default, so omitted in sparse serialization
        assert reply_result.get("message_type", "response") == "response"


class TestAgentAcknowledgeMessage:
    def test_agent_acknowledge_message_tool(self) -> None:
        send_result = json.loads(
            agent_send_message("alice", "bob", "read me", run_id="r1")
        )
        msg_id = send_result["message"]["id"]
        ack_result = json.loads(agent_acknowledge_message(msg_id))
        assert ack_result["ok"] is True
        assert ack_result["message_id"] == msg_id

    def test_acknowledge_nonexistent(self) -> None:
        ack_result = json.loads(agent_acknowledge_message("fake-id"))
        assert ack_result["ok"] is False

    def test_double_acknowledge(self) -> None:
        send_result = json.loads(
            agent_send_message("alice", "bob", "read me", run_id="r1")
        )
        msg_id = send_result["message"]["id"]
        first = json.loads(agent_acknowledge_message(msg_id))
        assert first["ok"] is True
        second = json.loads(agent_acknowledge_message(msg_id))
        assert second["ok"] is False


class TestRoundTrip:
    def test_send_then_receive_roundtrip(self) -> None:
        agent_send_message("auditor", "reviewer", "found 3 bugs", run_id="run-001",
                           step_id="audit", message_type="request")
        result = json.loads(agent_receive_messages("reviewer", "run-001"))
        assert len(result) == 1
        msg = result[0]
        assert msg["from_agent"] == "auditor"
        assert msg["content"] == "found 3 bugs"
        assert msg["message_type"] == "request"
        assert msg["step_id"] == "audit"
