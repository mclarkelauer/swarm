"""Tests for swarm.plan.conditions: validate_condition and evaluate_condition."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.plan.conditions import evaluate_condition, validate_condition


# ---------------------------------------------------------------------------
# validate_condition
# ---------------------------------------------------------------------------


class TestValidateConditionAlwaysValid:
    def test_empty_string_is_valid(self) -> None:
        assert validate_condition("") is None

    def test_always_is_valid(self) -> None:
        assert validate_condition("always") is None

    def test_never_is_valid(self) -> None:
        assert validate_condition("never") is None


class TestValidateConditionValidPrefixes:
    def test_artifact_exists_with_value(self) -> None:
        assert validate_condition("artifact_exists:output.md") is None

    def test_step_completed_with_value(self) -> None:
        assert validate_condition("step_completed:s1") is None

    def test_step_failed_with_value(self) -> None:
        assert validate_condition("step_failed:s2") is None

    def test_artifact_exists_with_nested_path(self) -> None:
        assert validate_condition("artifact_exists:reports/summary.md") is None


class TestValidateConditionKnownPrefixEmptyValue:
    def test_artifact_exists_empty_value_is_error(self) -> None:
        error = validate_condition("artifact_exists:")
        assert error is not None
        assert "artifact_exists:" in error
        assert "empty" in error.lower()

    def test_step_completed_empty_value_is_error(self) -> None:
        error = validate_condition("step_completed:")
        assert error is not None
        assert "step_completed:" in error
        assert "empty" in error.lower()

    def test_step_failed_empty_value_is_error(self) -> None:
        error = validate_condition("step_failed:")
        assert error is not None
        assert "step_failed:" in error
        assert "empty" in error.lower()


class TestValidateConditionUnknownFormat:
    def test_unknown_word_is_error(self) -> None:
        error = validate_condition("maybe_run:something")
        assert error is not None
        assert "Unknown condition format" in error

    def test_random_string_is_error(self) -> None:
        error = validate_condition("run_if_tuesday")
        assert error is not None

    def test_error_includes_valid_alternatives(self) -> None:
        error = validate_condition("unknown_prefix:value")
        assert error is not None
        # Should mention valid prefixes or keywords
        assert "always" in error or "artifact_exists" in error or "step_completed" in error


# ---------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------


class TestEvaluateConditionAlwaysExecute:
    def test_empty_string_returns_true(self) -> None:
        assert evaluate_condition("", set()) is True

    def test_always_returns_true(self) -> None:
        assert evaluate_condition("always", set()) is True

    def test_empty_with_populated_completed(self) -> None:
        assert evaluate_condition("", {"s1", "s2"}) is True


class TestEvaluateConditionNever:
    def test_never_returns_false(self) -> None:
        assert evaluate_condition("never", set()) is False

    def test_never_ignores_completed(self) -> None:
        assert evaluate_condition("never", {"s1", "s2", "s3"}) is False


class TestEvaluateConditionArtifactExists:
    def test_file_present_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "output.md").write_text("content", encoding="utf-8")
        assert evaluate_condition("artifact_exists:output.md", set(), artifacts_dir=tmp_path) is True

    def test_file_missing_returns_false(self, tmp_path: Path) -> None:
        assert evaluate_condition("artifact_exists:missing.md", set(), artifacts_dir=tmp_path) is False

    def test_artifacts_dir_none_returns_true_permissive(self) -> None:
        # Without an artifacts_dir, the check is skipped — permissive fallback
        assert evaluate_condition("artifact_exists:any_file.md", set(), artifacts_dir=None) is True

    def test_nested_path_file_present(self, tmp_path: Path) -> None:
        subdir = tmp_path / "reports"
        subdir.mkdir()
        (subdir / "summary.md").write_text("done", encoding="utf-8")
        assert (
            evaluate_condition("artifact_exists:reports/summary.md", set(), artifacts_dir=tmp_path)
            is True
        )

    def test_nested_path_file_missing(self, tmp_path: Path) -> None:
        assert (
            evaluate_condition("artifact_exists:reports/summary.md", set(), artifacts_dir=tmp_path)
            is False
        )


class TestEvaluateConditionStepCompleted:
    def test_step_in_completed_returns_true(self) -> None:
        assert evaluate_condition("step_completed:s1", {"s1", "s2"}) is True

    def test_step_not_in_completed_returns_false(self) -> None:
        assert evaluate_condition("step_completed:s1", {"s2", "s3"}) is False

    def test_empty_completed_set_returns_false(self) -> None:
        assert evaluate_condition("step_completed:s1", set()) is False


class TestEvaluateConditionStepFailed:
    def test_step_with_failed_outcome_returns_true(self) -> None:
        outcomes = {"s1": "failed", "s2": "completed"}
        assert evaluate_condition("step_failed:s1", set(), step_outcomes=outcomes) is True

    def test_step_with_completed_outcome_returns_false(self) -> None:
        outcomes = {"s1": "completed"}
        assert evaluate_condition("step_failed:s1", set(), step_outcomes=outcomes) is False

    def test_step_absent_from_outcomes_returns_false(self) -> None:
        outcomes: dict[str, str] = {"s2": "failed"}
        assert evaluate_condition("step_failed:s1", set(), step_outcomes=outcomes) is False

    def test_step_outcomes_none_returns_false(self) -> None:
        assert evaluate_condition("step_failed:s1", set(), step_outcomes=None) is False

    def test_step_outcomes_none_default_returns_false(self) -> None:
        # Default argument for step_outcomes is None
        assert evaluate_condition("step_failed:s1", {"s1"}) is False


class TestValidateConditionOutputContains:
    def test_valid_output_contains(self) -> None:
        assert validate_condition("output_contains:build:ERROR.*dependency") is None

    def test_valid_output_contains_simple_pattern(self) -> None:
        assert validate_condition("output_contains:step1:success") is None

    def test_missing_step_id_is_error(self) -> None:
        error = validate_condition("output_contains:")
        assert error is not None
        assert "empty" in error.lower()

    def test_missing_pattern_is_error(self) -> None:
        error = validate_condition("output_contains:step1:")
        assert error is not None
        assert "output_contains" in error

    def test_no_colon_separator_is_error(self) -> None:
        error = validate_condition("output_contains:step1_only")
        assert error is not None
        assert "output_contains" in error

    def test_invalid_regex_is_error(self) -> None:
        error = validate_condition("output_contains:step1:[invalid")
        assert error is not None
        assert "invalid regex" in error.lower() or "regex" in error.lower()

    def test_valid_complex_regex(self) -> None:
        assert validate_condition(r"output_contains:build:ERROR\s+\d{3}") is None


class TestEvaluateConditionOutputContains:
    def test_pattern_found_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "build.stdout.log").write_text(
            "Compiling...\nERROR: dependency not found\nDone.", encoding="utf-8"
        )
        assert (
            evaluate_condition(
                "output_contains:build:ERROR.*dependency",
                set(),
                artifacts_dir=tmp_path,
            )
            is True
        )

    def test_pattern_not_found_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "build.stdout.log").write_text(
            "Compiling...\nSuccess.\nDone.", encoding="utf-8"
        )
        assert (
            evaluate_condition(
                "output_contains:build:ERROR.*dependency",
                set(),
                artifacts_dir=tmp_path,
            )
            is False
        )

    def test_missing_log_file_returns_false(self, tmp_path: Path) -> None:
        assert (
            evaluate_condition(
                "output_contains:build:ERROR",
                set(),
                artifacts_dir=tmp_path,
            )
            is False
        )

    def test_artifacts_dir_none_returns_true_permissive(self) -> None:
        assert (
            evaluate_condition(
                "output_contains:build:ERROR",
                set(),
                artifacts_dir=None,
            )
            is True
        )

    def test_multiline_pattern_match(self, tmp_path: Path) -> None:
        (tmp_path / "test.stdout.log").write_text(
            "line1\nWARNING: deprecated API\nline3", encoding="utf-8"
        )
        assert (
            evaluate_condition(
                "output_contains:test:WARNING.*deprecated",
                set(),
                artifacts_dir=tmp_path,
            )
            is True
        )

    def test_malformed_condition_returns_false(self) -> None:
        # Missing pattern part
        assert evaluate_condition("output_contains:steponly", set()) is False


class TestEvaluateConditionUnknownFormat:
    def test_unknown_format_returns_true_permissive(self) -> None:
        # Unknown conditions evaluate permissively to True
        assert evaluate_condition("maybe_run:something", set()) is True

    def test_unknown_format_with_no_colon_returns_true(self) -> None:
        assert evaluate_condition("run_if_tuesday", set()) is True
