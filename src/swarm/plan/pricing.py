"""Model pricing table for fallback cost estimation.

Used by :func:`swarm.plan.executor._parse_cost_data` when the ``claude``
CLI emits token counts but no ``total_cost_usd`` field — for example,
older CLI versions or non-standard output formats.

Prices are USD per 1,000,000 tokens, sourced from Anthropic's published
pricing (https://www.anthropic.com/pricing) for the current model family.
The table is intentionally small and conservative; absent models fall
back to the Sonnet rate, which is the safest middle estimate for most
agent workloads.

Estimates are best-effort — they will not include cache discounts, batch
discounts, or beta-tier surcharges.  When the CLI reports a real
``total_cost_usd`` we always prefer that value.
"""

from __future__ import annotations

from typing import TypedDict


class ModelPrice(TypedDict):
    """USD per 1M tokens for a model, broken out by direction."""

    input_per_1m: float
    output_per_1m: float


# Anthropic public pricing as of 2026-04 (USD per 1M tokens).
# Cache pricing (creation/read) is omitted — the executor only sees
# aggregate counts and we treat them all as standard input tokens.
PRICING: dict[str, ModelPrice] = {
    # Claude 4 family
    "claude-opus-4": {"input_per_1m": 15.0, "output_per_1m": 75.0},
    "claude-opus-4-7": {"input_per_1m": 15.0, "output_per_1m": 75.0},
    "claude-sonnet-4": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "claude-sonnet-4-5": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "claude-sonnet-4-6": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "claude-haiku-4": {"input_per_1m": 1.0, "output_per_1m": 5.0},
    "claude-haiku-4-5": {"input_per_1m": 1.0, "output_per_1m": 5.0},
    # Legacy (Claude 3.x) — kept so older logs still parse.
    "claude-3-opus": {"input_per_1m": 15.0, "output_per_1m": 75.0},
    "claude-3-sonnet": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "claude-3-haiku": {"input_per_1m": 0.25, "output_per_1m": 1.25},
    "claude-3-5-sonnet": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "claude-3-5-haiku": {"input_per_1m": 1.0, "output_per_1m": 5.0},
}

# Sonnet rates are the conservative middle ground for unknown models.
_FALLBACK_PRICE: ModelPrice = {"input_per_1m": 3.0, "output_per_1m": 15.0}


def _normalize(model: str) -> str:
    """Strip context-window or beta suffixes (e.g. ``[1m]``) from a model id."""
    base = model.strip().lower()
    bracket = base.find("[")
    if bracket != -1:
        base = base[:bracket]
    return base.rstrip("-")


def lookup_price(model: str) -> ModelPrice:
    """Return the per-1M-token price for *model*, falling back to Sonnet rates.

    The lookup is tolerant of context-window suffixes (``claude-opus-4-7[1m]``
    matches ``claude-opus-4-7``) and of partial matches (``claude-sonnet-4-5-foo``
    matches ``claude-sonnet-4-5``).
    """
    if not model:
        return _FALLBACK_PRICE

    normalized = _normalize(model)
    if normalized in PRICING:
        return PRICING[normalized]

    # Longest-prefix fallback so e.g. an unknown variant of Sonnet still
    # gets Sonnet pricing rather than the generic default.
    for key in sorted(PRICING, key=len, reverse=True):
        if normalized.startswith(key):
            return PRICING[key]

    return _FALLBACK_PRICE


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts using :data:`PRICING`.

    Returns ``0.0`` when both counts are zero or negative.  Callers should
    only invoke this when the CLI did not report an authoritative cost.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return 0.0
    price = lookup_price(model)
    in_cost = max(input_tokens, 0) / 1_000_000 * price["input_per_1m"]
    out_cost = max(output_tokens, 0) / 1_000_000 * price["output_per_1m"]
    return in_cost + out_cost
