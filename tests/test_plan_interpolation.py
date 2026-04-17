"""Tests for the shared :func:`swarm.plan.interpolation.safe_interpolate` helper."""

from __future__ import annotations

from swarm.plan.interpolation import safe_interpolate


class TestReplaces:
    def test_known_key(self) -> None:
        assert safe_interpolate("Hello {name}!", {"name": "world"}) == "Hello world!"

    def test_multiple_keys(self) -> None:
        assert safe_interpolate("{a}-{b}", {"a": "x", "b": "y"}) == "x-y"

    def test_repeated_key(self) -> None:
        assert safe_interpolate("{x} {x} {x}", {"x": "go"}) == "go go go"


class TestPreserves:
    def test_unknown_key_left_intact(self) -> None:
        assert safe_interpolate("Hello {missing}!", {}) == "Hello {missing}!"

    def test_partial_replacement_keeps_unknowns(self) -> None:
        assert safe_interpolate("{a} and {b}", {"a": "alpha"}) == "alpha and {b}"

    def test_empty_template(self) -> None:
        assert safe_interpolate("", {"key": "val"}) == ""

    def test_empty_variables(self) -> None:
        assert safe_interpolate("no vars here", {}) == "no vars here"

    def test_non_word_placeholder_not_matched(self) -> None:
        # \w+ does not match dashes, so this remains literal.
        assert safe_interpolate("{key-with-dash}", {"key-with-dash": "NOPE"}) == "{key-with-dash}"

    def test_non_placeholder_braces_left_intact(self) -> None:
        assert safe_interpolate("a { b } c", {"b": "X"}) == "a { b } c"


class TestMappingSemantics:
    def test_accepts_arbitrary_mapping(self) -> None:
        # The signature is Mapping[str, str], not dict[...] specifically.
        from collections import OrderedDict

        ordered: OrderedDict[str, str] = OrderedDict([("a", "1"), ("b", "2")])
        assert safe_interpolate("{a}/{b}", ordered) == "1/2"
