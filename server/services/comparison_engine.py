"""Deterministic comparison logic; the LLM never calculates rankings itself."""

from typing import Any


def rank_quotes(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank price first, ETA second, adding a transparent one-based rank."""
    ranked = sorted(quotes, key=lambda quote: (quote["price_inr"], quote["eta_minutes"], quote["provider"]))
    return [{**quote, "rank": index} for index, quote in enumerate(ranked, start=1)]
