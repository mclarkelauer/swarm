"""Tests for message threading / negotiation support."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.messaging.api import MessageAPI


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[MessageAPI]:
    api = MessageAPI(tmp_path / "msg.db")
    try:
        yield api
    finally:
        api.close()


class TestGetThread:
    def test_thread_includes_original_and_replies(self, api: MessageAPI) -> None:
        msg = api.send("alice", "bob", "proposal: use React", run_id="r1")
        api.reply(msg.id, "bob", "counter: use Vue", run_id="r1")
        api.reply(msg.id, "alice", "accept: Vue is fine", run_id="r1")

        thread = api.get_thread(msg.id)
        assert len(thread) == 3
        assert thread[0].content == "proposal: use React"

    def test_thread_single_message(self, api: MessageAPI) -> None:
        msg = api.send("alice", "bob", "hello", run_id="r1")
        thread = api.get_thread(msg.id)
        assert len(thread) == 1

    def test_thread_nonexistent(self, api: MessageAPI) -> None:
        thread = api.get_thread("nonexistent-id")
        assert thread == []
