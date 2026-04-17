"""Tests for the shared :func:`swarm._fts.sanitize_fts_query` helper."""

from __future__ import annotations

from swarm._fts import sanitize_fts_query


class TestPrefixMode:
    """Default prefix=True wraps each token as ``"token"*``."""

    def test_simple_word(self) -> None:
        assert sanitize_fts_query("python") == '"python"*'

    def test_multiple_words(self) -> None:
        assert sanitize_fts_query("python test") == '"python"* "test"*'

    def test_hyphenated_word_preserved(self) -> None:
        # FTS5's default tokenizer splits on hyphens at match time;
        # the sanitizer keeps them in the literal token.
        assert sanitize_fts_query("code-reviewer") == '"code-reviewer"*'

    def test_empty_query(self) -> None:
        assert sanitize_fts_query("") == '""'

    def test_only_special_chars(self) -> None:
        assert sanitize_fts_query('***"()') == '""'


class TestExactMode:
    """prefix=False wraps each token as ``"token"`` with no glob suffix."""

    def test_simple_word(self) -> None:
        assert sanitize_fts_query("python", prefix=False) == '"python"'

    def test_multiple_words(self) -> None:
        assert sanitize_fts_query("python test", prefix=False) == '"python" "test"'

    def test_empty_query(self) -> None:
        assert sanitize_fts_query("", prefix=False) == '""'


class TestStripping:
    """Special characters and FTS5 operators are stripped before quoting."""

    def test_strips_double_quotes(self) -> None:
        assert sanitize_fts_query('he said "hi"') == '"he"* "said"* "hi"*'

    def test_strips_star(self) -> None:
        assert sanitize_fts_query("python*") == '"python"*'

    def test_strips_caret(self) -> None:
        assert sanitize_fts_query("^python") == '"python"*'

    def test_strips_parens(self) -> None:
        assert sanitize_fts_query("(python OR test)") == '"python"* "test"*'

    def test_strips_braces(self) -> None:
        assert sanitize_fts_query("{python}") == '"python"*'

    def test_strips_AND(self) -> None:
        assert sanitize_fts_query("python AND test") == '"python"* "test"*'

    def test_strips_OR(self) -> None:
        assert sanitize_fts_query("python OR test") == '"python"* "test"*'

    def test_strips_NOT(self) -> None:
        assert sanitize_fts_query("python NOT test") == '"python"* "test"*'

    def test_strips_NEAR(self) -> None:
        assert sanitize_fts_query("python NEAR test") == '"python"* "test"*'

    def test_case_insensitive_operator_stripping(self) -> None:
        assert sanitize_fts_query("python and test") == '"python"* "test"*'

    def test_strips_operators_in_exact_mode(self) -> None:
        assert sanitize_fts_query("python OR test", prefix=False) == '"python" "test"'


class TestSharedSemantics:
    """Both registry and memory routes flow through this helper."""

    def test_registry_wrapper_matches_shared_helper(self) -> None:
        from swarm.registry.api import _sanitize_fts_query as registry_sanitize

        assert registry_sanitize("review") == sanitize_fts_query("review", prefix=True)
        assert registry_sanitize("python test") == sanitize_fts_query(
            "python test", prefix=True,
        )

    def test_memory_wrapper_matches_shared_helper(self) -> None:
        from swarm.memory.api import _sanitize_fts_query as memory_sanitize

        # Memory now uses prefix=True for parity with the registry.
        assert memory_sanitize("review") == sanitize_fts_query("review", prefix=True)
        assert memory_sanitize("python test") == sanitize_fts_query(
            "python test", prefix=True,
        )
