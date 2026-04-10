"""Tests for Tier 5 missing MCP tools."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.mcp import state
from swarm.registry.api import RegistryAPI


@pytest.fixture(autouse=True)
def _setup(tmp_path: Path) -> None:
    state.registry_api = RegistryAPI(tmp_path / "reg.db")
    from swarm.memory.api import MemoryAPI

    state.memory_api = MemoryAPI(tmp_path / "mem.db")
    state.plans_dir = str(tmp_path)


class TestRegistryUpdate:
    def test_update_description(self) -> None:
        from swarm.mcp.registry_tools import registry_update

        assert state.registry_api is not None
        agent = state.registry_api.create("test", "prompt", [], [])
        result = json.loads(registry_update(agent.id, description="new desc"))
        assert result["description"] == "new desc"

    def test_update_status(self) -> None:
        from swarm.mcp.registry_tools import registry_update

        assert state.registry_api is not None
        agent = state.registry_api.create("test", "prompt", [], [])
        result = json.loads(registry_update(agent.id, status="deprecated"))
        assert result["status"] == "deprecated"

    def test_update_tags(self) -> None:
        from swarm.mcp.registry_tools import registry_update

        assert state.registry_api is not None
        agent = state.registry_api.create("test", "prompt", [], [])
        result = json.loads(registry_update(agent.id, tags="python, testing"))
        assert result["tags"] == ["python", "testing"]

    def test_update_not_found(self) -> None:
        from swarm.mcp.registry_tools import registry_update

        result = json.loads(registry_update("nonexistent"))
        assert "error" in result


class TestRegistryUpdateAPI:
    def test_update_allowed_fields(self, tmp_path: Path) -> None:
        api = RegistryAPI(tmp_path / "reg2.db")
        agent = api.create("test", "prompt", [], [])
        updated = api.update(agent.id, {"description": "updated", "notes": "new notes"})
        assert updated is not None
        assert updated.description == "updated"
        assert updated.notes == "new notes"

    def test_update_rejects_structural_fields(self, tmp_path: Path) -> None:
        api = RegistryAPI(tmp_path / "reg2.db")
        agent = api.create("test", "original prompt", [], [])
        updated = api.update(agent.id, {"system_prompt": "hacked"})
        assert updated is not None
        assert updated.system_prompt == "original prompt"  # unchanged

    def test_update_not_found(self, tmp_path: Path) -> None:
        api = RegistryAPI(tmp_path / "reg2.db")
        assert api.update("nonexistent", {"notes": "x"}) is None

    def test_update_tags_list(self, tmp_path: Path) -> None:
        api = RegistryAPI(tmp_path / "reg2.db")
        agent = api.create("test", "prompt", [], [])
        updated = api.update(agent.id, {"tags": ["a", "b"]})
        assert updated is not None
        assert list(updated.tags) == ["a", "b"]


class TestSwarmHealth:
    def test_health_returns_status(self) -> None:
        from swarm.mcp.discovery_tools import swarm_health

        result = json.loads(swarm_health())
        assert result["status"] == "ok"
        assert "agent_count" in result
        assert "memory_count" in result

    def test_health_includes_version(self) -> None:
        from swarm.mcp.discovery_tools import swarm_health

        result = json.loads(swarm_health())
        assert "version" in result


class TestPlanRemoveStep:
    def test_remove_step(self, tmp_path: Path) -> None:
        from swarm.mcp.plan_tools import plan_remove_step

        plan_data = {
            "version": 1,
            "goal": "test",
            "steps": [
                {"id": "a", "type": "task", "prompt": "a"},
                {"id": "b", "type": "task", "prompt": "b", "depends_on": ["a"]},
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_data))

        result = json.loads(plan_remove_step(str(plan_path), "a"))
        assert result["removed"] == "a"
        assert result["remaining_steps"] == 1

        # Verify depends_on was cleaned up
        reloaded = json.loads(plan_path.read_text())
        assert reloaded["steps"][0]["id"] == "b"
        assert "depends_on" not in reloaded["steps"][0] or reloaded["steps"][0].get("depends_on") == []

    def test_remove_nonexistent_step(self, tmp_path: Path) -> None:
        from swarm.mcp.plan_tools import plan_remove_step

        plan_data = {
            "version": 1,
            "goal": "test",
            "steps": [{"id": "a", "type": "task", "prompt": "a"}],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_data))

        result = json.loads(plan_remove_step(str(plan_path), "nonexistent"))
        assert "error" in result

    def test_remove_step_file_not_found(self) -> None:
        from swarm.mcp.plan_tools import plan_remove_step

        result = json.loads(plan_remove_step("/no/such/file.json", "a"))
        assert "error" in result


class TestPlanRunLogs:
    def test_empty_dir(self, tmp_path: Path) -> None:
        from swarm.mcp.executor_tools import plan_run_logs

        result = json.loads(plan_run_logs(str(tmp_path)))
        assert result == []

    def test_lists_run_logs(self, tmp_path: Path) -> None:
        from swarm.mcp.executor_tools import plan_run_logs

        log_data = {
            "plan_path": str(tmp_path / "plan_v1.json"),
            "plan_version": 1,
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T01:00:00",
            "status": "completed",
            "steps": [
                {
                    "step_id": "s1",
                    "status": "completed",
                    "started_at": "2026-01-01T00:00:00",
                    "finished_at": "2026-01-01T00:30:00",
                    "message": "",
                },
            ],
        }
        (tmp_path / "run_log.json").write_text(json.dumps(log_data))

        result = json.loads(plan_run_logs(str(tmp_path)))
        assert len(result) == 1
        assert result[0]["status"] == "completed"
        assert result[0]["steps_completed"] == 1
        assert result[0]["total_steps"] == 1

    def test_no_dir(self) -> None:
        from swarm.mcp.executor_tools import plan_run_logs

        result = json.loads(plan_run_logs("/no/such/dir"))
        assert result == []

    def test_default_plans_dir(self, tmp_path: Path) -> None:
        from swarm.mcp.executor_tools import plan_run_logs

        # state.plans_dir is set by fixture
        result = json.loads(plan_run_logs())
        assert isinstance(result, list)
