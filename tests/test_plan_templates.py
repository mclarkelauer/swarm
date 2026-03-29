"""Tests for swarm.plan.templates and the plan_template_* MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.errors import PlanError
from swarm.mcp import state
from swarm.mcp.plan_tools import plan_template_instantiate, plan_template_list
from swarm.plan.templates import (
    BUILTIN_TEMPLATES_DIR,
    USER_TEMPLATES_DIR,
    _safe_interpolate,
    instantiate_template,
    list_templates,
    load_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_template(templates_dir: Path, name: str, data: dict) -> Path:  # type: ignore[type-arg]
    """Write a JSON template file into a user-facing templates directory."""
    templates_dir.mkdir(parents=True, exist_ok=True)
    path = templates_dir / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


_MINIMAL_TEMPLATE = {
    "version": 1,
    "goal": "Do {task}",
    "variables": {"task": "something"},
    "steps": [
        {
            "id": "step1",
            "type": "task",
            "agent_type": "{agent}",
            "prompt": "Execute {task} using {agent}",
        }
    ],
}


# ---------------------------------------------------------------------------
# _safe_interpolate unit tests
# ---------------------------------------------------------------------------


class TestSafeInterpolate:
    def test_known_key_replaced(self) -> None:
        assert _safe_interpolate("Hello {name}!", {"name": "world"}) == "Hello world!"

    def test_unknown_key_left_intact(self) -> None:
        assert _safe_interpolate("Hello {unknown}!", {}) == "Hello {unknown}!"

    def test_partial_replacement(self) -> None:
        assert _safe_interpolate("{a} and {b}", {"a": "alpha"}) == "alpha and {b}"

    def test_empty_template(self) -> None:
        assert _safe_interpolate("", {"key": "val"}) == ""

    def test_multiple_occurrences(self) -> None:
        assert _safe_interpolate("{x} {x} {x}", {"x": "go"}) == "go go go"

    def test_non_word_chars_not_matched(self) -> None:
        # {key-with-dash} should not be matched by \w+ pattern
        result = _safe_interpolate("{key-with-dash}", {"key-with-dash": "NOPE"})
        assert result == "{key-with-dash}"


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------


class TestListTemplates:
    def test_finds_builtin_templates(self) -> None:
        """Builtin templates must always be discoverable."""
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "code-review" in names
        assert "feature-build" in names
        assert "security-audit" in names

    def test_builtin_source_label(self) -> None:
        templates = list_templates()
        builtins = {t["name"]: t for t in templates if t["source"] == "builtin"}
        assert "code-review" in builtins

    def test_template_metadata_shape(self) -> None:
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "goal" in t
            assert "step_count" in t
            assert "variables" in t
            assert "source" in t
            assert isinstance(t["step_count"], int)
            assert isinstance(t["variables"], list)

    def test_user_template_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A user template with same name as a builtin must shadow the builtin."""
        user_dir = tmp_path / "templates"
        custom = {
            "version": 1,
            "goal": "Custom code review",
            "variables": {"description": ""},
            "steps": [
                {
                    "id": "review",
                    "type": "task",
                    "agent_type": "custom-agent",
                    "prompt": "Custom review",
                }
            ],
        }
        _make_user_template(user_dir, "code-review", custom)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        templates = list_templates()
        by_name = {t["name"]: t for t in templates}
        assert by_name["code-review"]["source"] == "user"
        assert by_name["code-review"]["goal"] == "Custom code review"

    def test_user_only_template_appears(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Templates that only exist in the user dir must appear in results."""
        user_dir = tmp_path / "templates"
        data = {
            "version": 1,
            "goal": "My special workflow",
            "variables": {},
            "steps": [
                {
                    "id": "go",
                    "type": "task",
                    "agent_type": "specialist",
                    "prompt": "Do the thing",
                }
            ],
        }
        _make_user_template(user_dir, "my-workflow", data)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "my-workflow" in names

    def test_missing_user_dir_does_not_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If USER_TEMPLATES_DIR doesn't exist, list_templates still returns builtins."""
        monkeypatch.setattr(
            "swarm.plan.templates.USER_TEMPLATES_DIR", tmp_path / "nonexistent"
        )
        templates = list_templates()
        assert len(templates) >= 3  # at least the 3 builtins

    def test_malformed_template_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Malformed JSON in a template file must be skipped silently."""
        user_dir = tmp_path / "templates"
        user_dir.mkdir(parents=True)
        (user_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        # Should not raise; broken template just absent from results.
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "broken" not in names


# ---------------------------------------------------------------------------
# load_template
# ---------------------------------------------------------------------------


class TestLoadTemplate:
    def test_loads_builtin(self) -> None:
        plan = load_template("code-review")
        assert "code-review" in plan.goal.lower() or "Code review" in plan.goal

    def test_unknown_raises_plan_error(self) -> None:
        with pytest.raises(PlanError, match="not found"):
            load_template("nonexistent-template-xyz")

    def test_user_template_preferred_over_builtin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "templates"
        custom = {
            "version": 1,
            "goal": "Custom goal",
            "variables": {},
            "steps": [
                {
                    "id": "s1",
                    "type": "task",
                    "agent_type": "tester",
                    "prompt": "Custom step",
                }
            ],
        }
        _make_user_template(user_dir, "code-review", custom)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        plan = load_template("code-review")
        assert plan.goal == "Custom goal"


# ---------------------------------------------------------------------------
# instantiate_template
# ---------------------------------------------------------------------------


class TestInstantiateTemplate:
    def test_basic_instantiation_code_review(self) -> None:
        plan = instantiate_template("code-review", {"description": "auth module"})
        assert "auth module" in plan.goal
        assert plan.version == 1
        assert len(plan.steps) > 0

    def test_variables_interpolated_in_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "templates"
        _make_user_template(user_dir, "test-tpl", _MINIMAL_TEMPLATE)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        plan = instantiate_template("test-tpl", {"task": "deploy", "agent": "deployer"})
        assert "deploy" in plan.steps[0].prompt
        assert "deployer" in plan.steps[0].agent_type

    def test_unknown_placeholder_left_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "templates"
        tpl = {
            "version": 1,
            "goal": "Run {task}",
            "variables": {"task": ""},
            "steps": [
                {
                    "id": "run",
                    "type": "task",
                    "agent_type": "runner",
                    "prompt": "Run {task} in {unknown_var}",
                }
            ],
        }
        _make_user_template(user_dir, "partial-tpl", tpl)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        plan = instantiate_template("partial-tpl", {"task": "tests"})
        assert "{unknown_var}" in plan.steps[0].prompt
        assert "tests" in plan.steps[0].prompt

    def test_caller_variables_override_template_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "templates"
        tpl = {
            "version": 1,
            "goal": "Build {target}",
            "variables": {"target": "default-target"},
            "steps": [
                {
                    "id": "build",
                    "type": "task",
                    "agent_type": "builder",
                    "prompt": "Build {target}",
                }
            ],
        }
        _make_user_template(user_dir, "build-tpl", tpl)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        plan = instantiate_template("build-tpl", {"target": "my-service"})
        assert "my-service" in plan.steps[0].prompt
        assert "default-target" not in plan.steps[0].prompt

    def test_template_defaults_used_when_no_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "templates"
        tpl = {
            "version": 1,
            "goal": "Run {mode}",
            "variables": {"mode": "production"},
            "steps": [
                {
                    "id": "run",
                    "type": "task",
                    "agent_type": "runner",
                    "prompt": "Run in {mode}",
                }
            ],
        }
        _make_user_template(user_dir, "mode-tpl", tpl)
        monkeypatch.setattr("swarm.plan.templates.USER_TEMPLATES_DIR", user_dir)

        plan = instantiate_template("mode-tpl", {})
        assert "production" in plan.steps[0].prompt

    def test_unknown_template_raises_plan_error(self) -> None:
        with pytest.raises(PlanError, match="not found"):
            instantiate_template("does-not-exist", {})

    def test_goal_interpolated(self) -> None:
        plan = instantiate_template("feature-build", {"description": "user login"})
        assert "user login" in plan.goal

    def test_version_set_to_one(self) -> None:
        plan = instantiate_template("security-audit", {"description": "API layer"})
        assert plan.version == 1

    def test_all_builtins_instantiate_cleanly(self) -> None:
        for name in ("code-review", "feature-build", "security-audit"):
            plan = instantiate_template(name, {"description": "test", "project_dir": "/tmp"})
            assert plan.version == 1
            assert len(plan.steps) > 0


# ---------------------------------------------------------------------------
# MCP tool: plan_template_list
# ---------------------------------------------------------------------------


class TestPlanTemplateListTool:
    def test_returns_json_array(self) -> None:
        result = json.loads(plan_template_list())
        assert isinstance(result, list)
        assert len(result) >= 3

    def test_contains_builtin_names(self) -> None:
        result = json.loads(plan_template_list())
        names = {t["name"] for t in result}
        assert "code-review" in names
        assert "feature-build" in names
        assert "security-audit" in names

    def test_each_entry_has_required_keys(self) -> None:
        result = json.loads(plan_template_list())
        for item in result:
            assert "name" in item
            assert "goal" in item
            assert "step_count" in item
            assert "variables" in item
            assert "source" in item


# ---------------------------------------------------------------------------
# MCP tool: plan_template_instantiate
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path) -> None:
    state.plans_dir = str(tmp_path)


class TestPlanTemplateInstantiateTool:
    def test_saves_plan_and_returns_path(self, tmp_path: Path) -> None:
        result = json.loads(
            plan_template_instantiate(
                "code-review",
                json.dumps({"description": "auth module"}),
            )
        )
        assert result["errors"] == []
        assert result["version"] == 1
        assert Path(result["path"]).exists()

    def test_custom_plans_dir(self, tmp_path: Path) -> None:
        custom = tmp_path / "my_plans"
        custom.mkdir()
        result = json.loads(
            plan_template_instantiate(
                "feature-build",
                json.dumps({"description": "payments"}),
                plans_dir=str(custom),
            )
        )
        assert result["errors"] == []
        assert str(custom) in result["path"]

    def test_variables_applied(self, tmp_path: Path) -> None:
        result = json.loads(
            plan_template_instantiate(
                "security-audit",
                json.dumps({"description": "OAuth flow", "project_dir": "/srv/app"}),
            )
        )
        assert result["errors"] == []
        plan_path = Path(result["path"])
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        # Description must appear somewhere in step prompts
        prompts = " ".join(s["prompt"] for s in plan_data["steps"])
        assert "OAuth flow" in prompts
        assert "/srv/app" in prompts

    def test_invalid_variables_json_returns_error(self) -> None:
        result = json.loads(
            plan_template_instantiate("code-review", "{not valid json}")
        )
        assert "error" in result
        assert "Invalid variables_json" in result["error"]

    def test_unknown_template_returns_error(self) -> None:
        result = json.loads(
            plan_template_instantiate("no-such-template", "{}")
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_default_empty_variables_json(self, tmp_path: Path) -> None:
        """Omitting variables_json should succeed using template defaults."""
        result = json.loads(plan_template_instantiate("code-review"))
        assert result["errors"] == []
        assert Path(result["path"]).exists()
