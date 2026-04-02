"""Tests for swarm.messaging.models: AgentMessage."""

from __future__ import annotations

import pytest

from swarm.messaging.models import AgentMessage


class TestAgentMessageConstruction:
    def test_all_fields(self) -> None:
        msg = AgentMessage(
            id="abc-123",
            from_agent="sender",
            to_agent="receiver",
            step_id="s1",
            run_id="r1",
            content="payload",
            message_type="request",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert msg.id == "abc-123"
        assert msg.from_agent == "sender"
        assert msg.to_agent == "receiver"
        assert msg.step_id == "s1"
        assert msg.run_id == "r1"
        assert msg.content == "payload"
        assert msg.message_type == "request"
        assert msg.created_at == "2026-01-01T00:00:00+00:00"

    def test_defaults(self) -> None:
        msg = AgentMessage(id="x", from_agent="a", to_agent="b")
        assert msg.step_id == ""
        assert msg.run_id == ""
        assert msg.content == ""
        assert msg.message_type == "response"
        assert msg.created_at == ""


class TestAgentMessageFrozen:
    def test_cannot_assign_attributes(self) -> None:
        msg = AgentMessage(id="f1", from_agent="a", to_agent="b")
        with pytest.raises(AttributeError):
            msg.content = "modified"  # type: ignore[misc]

    def test_cannot_assign_id(self) -> None:
        msg = AgentMessage(id="f1", from_agent="a", to_agent="b")
        with pytest.raises(AttributeError):
            msg.id = "new-id"  # type: ignore[misc]


class TestAgentMessageSparseSerialization:
    def test_minimal_dict(self) -> None:
        msg = AgentMessage(id="s1", from_agent="a", to_agent="b")
        d = msg.to_dict()
        assert set(d.keys()) == {"id", "from_agent", "to_agent"}

    def test_default_message_type_omitted(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", message_type="response")
        d = msg.to_dict()
        assert "message_type" not in d

    def test_non_default_message_type_included(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", message_type="request")
        d = msg.to_dict()
        assert d["message_type"] == "request"

    def test_broadcast_message_type_included(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="*", message_type="broadcast")
        d = msg.to_dict()
        assert d["message_type"] == "broadcast"

    def test_empty_step_id_omitted(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", step_id="")
        d = msg.to_dict()
        assert "step_id" not in d

    def test_non_empty_step_id_included(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", step_id="s1")
        d = msg.to_dict()
        assert d["step_id"] == "s1"

    def test_empty_content_omitted(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", content="")
        d = msg.to_dict()
        assert "content" not in d

    def test_non_empty_content_included(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", content="hello")
        d = msg.to_dict()
        assert d["content"] == "hello"

    def test_empty_created_at_omitted(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", created_at="")
        d = msg.to_dict()
        assert "created_at" not in d

    def test_non_empty_created_at_included(self) -> None:
        msg = AgentMessage(id="1", from_agent="a", to_agent="b", created_at="2026-01-01")
        d = msg.to_dict()
        assert d["created_at"] == "2026-01-01"


class TestAgentMessageRoundTrip:
    def test_full_roundtrip(self) -> None:
        original = AgentMessage(
            id="x",
            from_agent="sender",
            to_agent="receiver",
            step_id="step-1",
            run_id="run-1",
            content="payload",
            message_type="request",
            created_at="2026-01-01",
        )
        restored = AgentMessage.from_dict(original.to_dict())
        assert restored == original

    def test_default_roundtrip(self) -> None:
        original = AgentMessage(id="y", from_agent="a", to_agent="b")
        restored = AgentMessage.from_dict(original.to_dict())
        assert restored == original


class TestAgentMessageFromDictBackwardCompat:
    def test_missing_optional_fields(self) -> None:
        d = {"id": "old-id", "from_agent": "a", "to_agent": "b"}
        msg = AgentMessage.from_dict(d)
        assert msg.step_id == ""
        assert msg.run_id == ""
        assert msg.content == ""
        assert msg.message_type == "response"
        assert msg.created_at == ""

    def test_partial_optional_fields(self) -> None:
        d = {
            "id": "partial",
            "from_agent": "a",
            "to_agent": "b",
            "message_type": "broadcast",
        }
        msg = AgentMessage.from_dict(d)
        assert msg.message_type == "broadcast"
        assert msg.step_id == ""
        assert msg.run_id == ""


class TestAgentMessageCreate:
    def test_uuid_generated(self) -> None:
        msg = AgentMessage.create(from_agent="a", to_agent="b", content="hi")
        assert msg.id
        assert len(msg.id) == 36  # UUID format

    def test_fields_passed_through(self) -> None:
        msg = AgentMessage.create(
            from_agent="sender",
            to_agent="receiver",
            content="data",
            message_type="request",
            step_id="s1",
            run_id="r1",
            created_at="2026-01-01",
        )
        assert msg.from_agent == "sender"
        assert msg.to_agent == "receiver"
        assert msg.content == "data"
        assert msg.message_type == "request"
        assert msg.step_id == "s1"
        assert msg.run_id == "r1"
        assert msg.created_at == "2026-01-01"

    def test_defaults(self) -> None:
        msg = AgentMessage.create(from_agent="a", to_agent="b", content="c")
        assert msg.message_type == "response"
        assert msg.step_id == ""
        assert msg.run_id == ""

    def test_unique_ids(self) -> None:
        m1 = AgentMessage.create(from_agent="a", to_agent="b", content="c")
        m2 = AgentMessage.create(from_agent="a", to_agent="b", content="c")
        assert m1.id != m2.id
