"""Tests for swarm.context.api: SharedContextAPI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from swarm.context.api import SharedContextAPI


@pytest.fixture()
def api(tmp_path: Path) -> Iterator[SharedContextAPI]:
    api = SharedContextAPI(tmp_path / "context.db")
    try:
        yield api
    finally:
        api.close()


class TestSetAndGet:
    def test_set_and_get(self, api: SharedContextAPI) -> None:
        api.set("run-1", "api_schema", '{"endpoints": ["/foo"]}', set_by="agent-a")
        value = api.get("run-1", "api_schema")
        assert value == '{"endpoints": ["/foo"]}'

    def test_get_nonexistent_returns_none(self, api: SharedContextAPI) -> None:
        value = api.get("run-1", "missing_key")
        assert value is None


class TestGetAll:
    def test_get_all(self, api: SharedContextAPI) -> None:
        api.set("run-1", "key_a", "value_a")
        api.set("run-1", "key_b", "value_b")
        api.set("run-1", "key_c", "value_c")
        result = api.get_all("run-1")
        assert result == {"key_a": "value_a", "key_b": "value_b", "key_c": "value_c"}

    def test_get_all_empty(self, api: SharedContextAPI) -> None:
        result = api.get_all("run-empty")
        assert result == {}


class TestDelete:
    def test_delete(self, api: SharedContextAPI) -> None:
        api.set("run-1", "temp", "data")
        assert api.delete("run-1", "temp") is True
        assert api.get("run-1", "temp") is None

    def test_delete_nonexistent_returns_false(self, api: SharedContextAPI) -> None:
        assert api.delete("run-1", "nope") is False


class TestClear:
    def test_clear(self, api: SharedContextAPI) -> None:
        api.set("run-1", "a", "1")
        api.set("run-1", "b", "2")
        api.set("run-1", "c", "3")
        count = api.clear("run-1")
        assert count == 3
        assert api.get_all("run-1") == {}

    def test_clear_empty_run(self, api: SharedContextAPI) -> None:
        count = api.clear("run-empty")
        assert count == 0


class TestOverwrite:
    def test_set_overwrites(self, api: SharedContextAPI) -> None:
        api.set("run-1", "key", "first")
        api.set("run-1", "key", "second")
        assert api.get("run-1", "key") == "second"


class TestRunIsolation:
    def test_isolation_between_runs(self, api: SharedContextAPI) -> None:
        api.set("run-1", "shared_key", "run1_value")
        api.set("run-2", "shared_key", "run2_value")
        assert api.get("run-1", "shared_key") == "run1_value"
        assert api.get("run-2", "shared_key") == "run2_value"

    def test_clear_does_not_affect_other_runs(self, api: SharedContextAPI) -> None:
        api.set("run-1", "key", "val1")
        api.set("run-2", "key", "val2")
        api.clear("run-1")
        assert api.get("run-1", "key") is None
        assert api.get("run-2", "key") == "val2"


class TestSetBy:
    def test_set_records_set_by(self, api: SharedContextAPI) -> None:
        result = api.set("run-1", "findings", "some data", set_by="researcher")
        assert result["set_by"] == "researcher"
        assert result["key"] == "findings"
        assert result["value"] == "some data"
        assert result["run_id"] == "run-1"
        assert "set_at" in result

    def test_set_by_defaults_to_empty(self, api: SharedContextAPI) -> None:
        result = api.set("run-1", "k", "v")
        assert result["set_by"] == ""
