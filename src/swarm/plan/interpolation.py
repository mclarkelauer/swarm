"""Shared safe ``{key}`` placeholder interpolation for plan prompts.

Single source of truth for the ``{name}`` substitution behaviour used by
plan templates, the executor, and the MCP plan tools.  Unknown keys are
left intact (no ``KeyError``) and only ``\\w+`` style identifiers are
considered placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def safe_interpolate(template: str, variables: Mapping[str, str]) -> str:
    """Interpolate ``{key}`` placeholders in *template* from *variables*.

    Keys absent from *variables* are left as-is; placeholders containing
    characters outside ``\\w`` (e.g. dashes) are not matched at all.

    Args:
        template: Source string containing zero or more ``{key}`` tokens.
        variables: Mapping of placeholder name to replacement value.

    Returns:
        The interpolated string.
    """
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(_replacer, template)
