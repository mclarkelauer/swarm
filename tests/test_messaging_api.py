"""Tests for swarm.messaging.api: MessageAPI."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swarm.messaging.api import MessageAPI
from swarm.messaging.models import AgentMessage


@pytest.fixture()
def api(tmp_path: Path) -> MessageAPI:
    return MessageAPI(tmp_path / "messages.db")


class TestSend:
    def test_send_returns_agent_message(self, api: MessageAPI) -> None:
        msg = api.send("agent-a", "agent-b", "hello")
        assert isinstance(msg, AgentMessage)
        assert msg.from_agent == "agent-a"
        assert msg.to_agent == "agent-b"
        assert msg.content == "hello"

    def test_send_generates_uuid(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "content")
        assert msg.id
        assert len(msg.id) == 36

    def test_send_auto_fills_created_at(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "content")
        assert msg.created_at
        dt = datetime.fromisoformat(msg.created_at)
        assert dt.tzinfo is not None

    def test_send_default_message_type(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "content")
        assert msg.message_type == "response"

    def test_send_custom_message_type(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "content", message_type="request")
        assert msg.message_type == "request"

    def test_send_with_step_and_run(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "content", step_id="s1", run_id="r1")
        assert msg.step_id == "s1"
        assert msg.run_id == "r1"

    def test_send_persists_to_db(self, api: MessageAPI) -> None:
        msg = api.send("a", "b", "persisted", run_id="r1")
        # Read back via raw SQL
        row = api._conn.execute(
            "SELECT content FROM messages WHERE id = ?", (msg.id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "persisted"


class TestReceive:
    def test_receive_returns_direct_messages(self, api: MessageAPI) -> None:
        api.send("sender", "receiver", "msg1", run_id="r1")
        api.send("sender", "other", "msg2", run_id="r1")
        msgs = api.receive("receiver", "r1")
        assert len(msgs) == 1
        assert msgs[0].content == "msg1"

    def test_receive_includes_broadcasts(self, api: MessageAPI) -> None:
        api.send("sender", "receiver", "direct", run_id="r1")
        api.broadcast("sender", "broadcast-msg", run_id="r1")
        msgs = api.receive("receiver", "r1")
        assert len(msgs) == 2

    def test_receive_filters_by_run_id(self, api: MessageAPI) -> None:
        api.send("a", "b", "run1-msg", run_id="r1")
        api.send("a", "b", "run2-msg", run_id="r2")
        msgs = api.receive("b", "r1")
        assert len(msgs) == 1
        assert msgs[0].content == "run1-msg"

    def test_receive_since_filter(self, api: MessageAPI) -> None:
        m1 = api.send("a", "b", "old", run_id="r1")
        # Small delay to ensure different timestamps
        time.sleep(0.01)
        m2 = api.send("a", "b", "new", run_id="r1")
        msgs = api.receive("b", "r1", since=m1.created_at)
        assert len(msgs) == 1
        assert msgs[0].content == "new"

    def test_receive_respects_limit(self, api: MessageAPI) -> None:
        for i in range(10):
            api.send("a", "b", f"msg-{i}", run_id="r1")
        msgs = api.receive("b", "r1", limit=3)
        assert len(msgs) == 3

    def test_receive_newest_first(self, api: MessageAPI) -> None:
        api.send("a", "b", "first", run_id="r1")
        time.sleep(0.01)
        api.send("a", "b", "second", run_id="r1")
        msgs = api.receive("b", "r1")
        assert msgs[0].content == "second"
        assert msgs[1].content == "first"

    def test_receive_empty_when_no_messages(self, api: MessageAPI) -> None:
        msgs = api.receive("nobody", "r1")
        assert msgs == []


class TestBroadcast:
    def test_broadcast_sets_to_agent_star(self, api: MessageAPI) -> None:
        msg = api.broadcast("sender", "hello all")
        assert msg.to_agent == "*"

    def test_broadcast_sets_message_type(self, api: MessageAPI) -> None:
        msg = api.broadcast("sender", "hello all")
        assert msg.message_type == "broadcast"

    def test_broadcast_with_step_and_run(self, api: MessageAPI) -> None:
        msg = api.broadcast("sender", "data", step_id="s1", run_id="r1")
        assert msg.step_id == "s1"
        assert msg.run_id == "r1"

    def test_broadcast_visible_to_all_receivers(self, api: MessageAPI) -> None:
        api.broadcast("sender", "for everyone", run_id="r1")
        msgs_a = api.receive("agent-a", "r1")
        msgs_b = api.receive("agent-b", "r1")
        assert len(msgs_a) == 1
        assert len(msgs_b) == 1
        assert msgs_a[0].content == "for everyone"


class TestListByRun:
    def test_list_by_run_returns_all_messages(self, api: MessageAPI) -> None:
        api.send("a", "b", "msg1", run_id="r1")
        api.send("c", "d", "msg2", run_id="r1")
        api.send("e", "f", "msg3", run_id="r2")
        msgs = api.list_by_run("r1")
        assert len(msgs) == 2

    def test_list_by_run_ordered_ascending(self, api: MessageAPI) -> None:
        api.send("a", "b", "first", run_id="r1")
        time.sleep(0.01)
        api.send("a", "b", "second", run_id="r1")
        msgs = api.list_by_run("r1")
        assert msgs[0].content == "first"
        assert msgs[1].content == "second"

    def test_list_by_run_empty(self, api: MessageAPI) -> None:
        msgs = api.list_by_run("nonexistent")
        assert msgs == []


class TestListByStep:
    def test_list_by_step_filters_correctly(self, api: MessageAPI) -> None:
        api.send("a", "b", "from-s1", step_id="s1", run_id="r1")
        api.send("a", "b", "from-s2", step_id="s2", run_id="r1")
        msgs = api.list_by_step("s1")
        assert len(msgs) == 1
        assert msgs[0].content == "from-s1"

    def test_list_by_step_with_run_id(self, api: MessageAPI) -> None:
        api.send("a", "b", "r1-s1", step_id="s1", run_id="r1")
        api.send("a", "b", "r2-s1", step_id="s1", run_id="r2")
        msgs = api.list_by_step("s1", run_id="r1")
        assert len(msgs) == 1
        assert msgs[0].content == "r1-s1"

    def test_list_by_step_ordered_ascending(self, api: MessageAPI) -> None:
        api.send("a", "b", "first", step_id="s1", run_id="r1")
        time.sleep(0.01)
        api.send("a", "b", "second", step_id="s1", run_id="r1")
        msgs = api.list_by_step("s1")
        assert msgs[0].content == "first"
        assert msgs[1].content == "second"

    def test_list_by_step_empty(self, api: MessageAPI) -> None:
        msgs = api.list_by_step("nonexistent")
        assert msgs == []


class TestClose:
    def test_close_closes_connection(self, api: MessageAPI) -> None:
        api.close()
        # After close, operations should fail
        with pytest.raises(Exception):
            api.send("a", "b", "should fail")


class TestConcurrency:
    def test_two_instances_same_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        api1 = MessageAPI(db_path)
        api2 = MessageAPI(db_path)
        api1.send("a", "b", "from-api1", run_id="r1")
        # api2 can read what api1 wrote (WAL mode)
        msgs = api2.receive("b", "r1")
        assert len(msgs) == 1
        assert msgs[0].content == "from-api1"
        api1.close()
        api2.close()
