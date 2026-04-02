"""Conditional step gating for execution plans."""

from __future__ import annotations

import re
from pathlib import Path

_KNOWN_PREFIXES = (
    "artifact_exists:",
    "step_completed:",
    "step_failed:",
    "iteration_ge:",
    "output_contains:",
)


def validate_condition(condition: str) -> str | None:
    """Return an error message if the condition expression is invalid, else None.

    Valid expressions:
    - ``""`` (empty) — always execute
    - ``"always"`` — always execute (explicit)
    - ``"never"`` — skip this step
    - ``"artifact_exists:<path>"`` — non-empty path required
    - ``"step_completed:<step_id>"`` — non-empty step ID required
    - ``"step_failed:<step_id>"`` — non-empty step ID required
    - ``"iteration_ge:<N>"`` — positive integer N required
    """
    if condition in ("", "always", "never"):
        return None

    for prefix in _KNOWN_PREFIXES:
        if condition.startswith(prefix):
            value = condition[len(prefix):]
            if not value:
                return (
                    f"Condition '{condition}' uses prefix '{prefix}' "
                    f"but has an empty value after the colon"
                )
            # Extra validation for iteration_ge: value must be a positive int
            if prefix == "iteration_ge:":
                try:
                    n = int(value)
                except ValueError:
                    return (
                        f"Condition '{condition}': value after 'iteration_ge:' "
                        f"must be a positive integer, got '{value}'"
                    )
                if n < 1:
                    return (
                        f"Condition '{condition}': value after 'iteration_ge:' "
                        f"must be a positive integer (>= 1), got {n}"
                    )
            # Extra validation for output_contains: format is step_id:regex
            if prefix == "output_contains:":
                parts = value.split(":", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    return (
                        f"Condition '{condition}': output_contains requires format "
                        f"'output_contains:<step_id>:<regex_pattern>'"
                    )
                try:
                    re.compile(parts[1])
                except re.error as exc:
                    return (
                        f"Condition '{condition}': invalid regex pattern: {exc}"
                    )
            return None

    # Unknown format — treated as permissive at evaluation time, but warn at
    # validation time so plan authors discover typos early.
    return (
        f"Unknown condition format '{condition}'; "
        f"valid prefixes are: {', '.join(_KNOWN_PREFIXES)}, "
        f"or use 'always' / 'never'"
    )


def evaluate_condition(
    condition: str,
    completed: set[str],
    step_outcomes: dict[str, str] | None = None,
    artifacts_dir: Path | None = None,
    iteration: int | None = None,
) -> bool:
    """Return True if the step should execute given the current runtime state.

    Args:
        condition: The condition expression from the step definition.
        completed: Set of step IDs that have already completed successfully.
        step_outcomes: Optional mapping of step ID to outcome string (e.g.
            ``"failed"``, ``"skipped"``).  Required for ``step_failed:``
            evaluation; when ``None``, ``step_failed:`` always returns False.
        artifacts_dir: Base directory for resolving ``artifact_exists:`` paths.
            When ``None``, the check is skipped and the condition evaluates to
            True (permissive fallback).
        iteration: Current loop iteration count.  Required for
            ``iteration_ge:`` evaluation; when ``None``, the condition
            evaluates to False.

    Returns:
        True if the step should be executed, False if it should be skipped.
    """
    if condition in ("", "always"):
        return True

    if condition == "never":
        return False

    if condition.startswith("artifact_exists:"):
        path = condition[len("artifact_exists:"):]
        if artifacts_dir is None:
            return True
        return (artifacts_dir / path).exists()

    if condition.startswith("step_completed:"):
        step_id = condition[len("step_completed:"):]
        return step_id in completed

    if condition.startswith("step_failed:"):
        step_id = condition[len("step_failed:"):]
        if step_outcomes is None:
            return False
        return step_outcomes.get(step_id) == "failed"

    if condition.startswith("iteration_ge:"):
        value = condition[len("iteration_ge:"):]
        if iteration is None:
            return False
        try:
            n = int(value)
        except ValueError:
            return False
        return iteration >= n

    if condition.startswith("output_contains:"):
        rest = condition[len("output_contains:"):]
        parts = rest.split(":", 1)
        if len(parts) != 2:
            return False
        step_id, pattern = parts
        if artifacts_dir is None:
            return True  # permissive fallback
        log_path = artifacts_dir / f"{step_id}.stdout.log"
        if not log_path.exists():
            return False
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return re.search(pattern, content) is not None

    # Unknown format — permissive default
    return True
