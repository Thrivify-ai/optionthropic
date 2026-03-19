"""
Pure helper utilities used by analytics modules.

These functions intentionally avoid third-party imports so they can be unit
tested without requiring the full backend dependency stack.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def pcr_sentiment_from_value(pcr_oi: float | None) -> str:
    if pcr_oi is None:
        return "NEUTRAL"
    if pcr_oi > 1.3:
        return "BULLISH"
    if pcr_oi < 0.7:
        return "BEARISH"
    return "NEUTRAL"


def select_representative_expiry(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Prefer the nearest upcoming expiry. If all expiries are in the past, use the
    most recent one. This matches how intraday options analytics usually anchor
    to the front contract.
    """
    today = date.today()
    future_or_today = [row for row in results if row["expiry"] >= today]
    if future_or_today:
        return min(future_or_today, key=lambda row: row["expiry"])
    return max(results, key=lambda row: row["expiry"])


def determine_dominant_flow(total_call_premium: float, total_put_premium: float) -> str:
    """
    We only store snapshots, not aggressor-side trades, so dominant flow is an
    inference from premium imbalance. We keep the existing vocabulary expected
    by downstream logic for backward compatibility.
    """
    if total_put_premium > total_call_premium * 1.5:
        return "put_writing"
    if total_call_premium > total_put_premium * 1.5:
        return "call_writing"
    if total_put_premium > total_call_premium * 1.1:
        return "put_buying"
    if total_call_premium > total_put_premium * 1.1:
        return "call_buying"
    return "mixed"
