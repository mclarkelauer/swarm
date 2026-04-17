"""Tests for the model pricing fallback table."""

from __future__ import annotations

import pytest

from swarm.plan.pricing import (
    PRICING,
    estimate_cost_usd,
    lookup_price,
)


class TestLookupPrice:
    def test_known_model_returns_exact_entry(self) -> None:
        price = lookup_price("claude-opus-4-7")
        assert price == PRICING["claude-opus-4-7"]

    def test_strips_context_window_suffix(self) -> None:
        price = lookup_price("claude-opus-4-7[1m]")
        assert price == PRICING["claude-opus-4-7"]

    def test_case_insensitive(self) -> None:
        price = lookup_price("Claude-Sonnet-4-5")
        assert price == PRICING["claude-sonnet-4-5"]

    def test_unknown_variant_uses_longest_prefix(self) -> None:
        # "claude-sonnet-4-5-experimental" is unknown, but the prefix
        # matcher should still hit the Sonnet-4-5 entry.
        price = lookup_price("claude-sonnet-4-5-experimental")
        assert price == PRICING["claude-sonnet-4-5"]

    def test_unknown_model_falls_back_to_sonnet_rates(self) -> None:
        price = lookup_price("totally-unknown-model")
        assert price == {"input_per_1m": 3.0, "output_per_1m": 15.0}

    def test_empty_model_falls_back_to_sonnet_rates(self) -> None:
        price = lookup_price("")
        assert price["input_per_1m"] == 3.0
        assert price["output_per_1m"] == 15.0


class TestEstimateCostUsd:
    def test_zero_tokens_returns_zero(self) -> None:
        assert estimate_cost_usd("claude-opus-4-7", 0, 0) == 0.0

    def test_negative_tokens_treated_as_zero(self) -> None:
        assert estimate_cost_usd("claude-opus-4-7", -5, -10) == 0.0

    def test_opus_pricing(self) -> None:
        # 1M input @ $15 + 1M output @ $75 = $90
        cost = estimate_cost_usd("claude-opus-4-7", 1_000_000, 1_000_000)
        assert cost == pytest.approx(90.0)

    def test_sonnet_pricing(self) -> None:
        # 1M input @ $3 + 1M output @ $15 = $18
        cost = estimate_cost_usd("claude-sonnet-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_haiku_pricing(self) -> None:
        # 1M input @ $1 + 1M output @ $5 = $6
        cost = estimate_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(6.0)

    def test_partial_million_tokens(self) -> None:
        # 100k input @ $3/M + 50k output @ $15/M = 0.30 + 0.75 = 1.05
        cost = estimate_cost_usd("claude-sonnet-4-5", 100_000, 50_000)
        assert cost == pytest.approx(1.05)

    def test_unknown_model_uses_sonnet_fallback(self) -> None:
        cost = estimate_cost_usd("mystery-model", 1_000_000, 0)
        assert cost == pytest.approx(3.0)
