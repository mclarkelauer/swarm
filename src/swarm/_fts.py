"""Shared FTS5 query sanitization.

Single source of truth for converting a user-supplied search string into a
safe ``MATCH`` expression.  Both :mod:`swarm.registry.api` and
:mod:`swarm.memory.api` route through :func:`sanitize_fts_query` so the
two databases share identical operator-stripping and prefix-matching
semantics.
"""

from __future__ import annotations

import re

# FTS5 special characters that would otherwise be interpreted as operators
# or grouping syntax.  Stripping them prevents both injection and accidental
# parse errors from quoted-but-unterminated user input.
_SPECIAL_CHAR_RE = re.compile(r'[*^"(){}]')
_OPERATOR_RE = re.compile(r"\b(AND|OR|NOT|NEAR)\b", flags=re.IGNORECASE)


def sanitize_fts_query(raw: str, *, prefix: bool = True) -> str:
    """Convert a user query string into a safe FTS5 ``MATCH`` expression.

    - Strips FTS5 operators (``AND``/``OR``/``NOT``/``NEAR``) and grouping
      special characters (``*``, ``^``, ``"``, ``()``, ``{}``).
    - Wraps each surviving token in double-quotes so embedded punctuation
      cannot reopen the operator grammar.
    - When *prefix* is true (the default) appends ``*`` to each quoted
      token so ``"review"*`` matches ``reviewer``.
    - Joins tokens with whitespace, which FTS5 treats as implicit ``AND``.

    Examples:
        >>> sanitize_fts_query("python test")
        '"python"* "test"*'
        >>> sanitize_fts_query("python test", prefix=False)
        '"python" "test"'
        >>> sanitize_fts_query("")
        '""'
    """
    cleaned = _SPECIAL_CHAR_RE.sub(" ", raw)
    cleaned = _OPERATOR_RE.sub(" ", cleaned)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    suffix = "*" if prefix else ""
    return " ".join(f'"{token}"{suffix}' for token in tokens)
