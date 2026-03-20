"""
Pure helpers for shaping cached dashboard payloads.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.analytics.main_signal_logic import derive_signal_context


def serialize_trading_signal_payload(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {
            "signal": "Wait",
            "confidence": 0,
            "support": None,
            "resistance": None,
            "bias_5m": "Neutral",
            "bias_30m": "Neutral",
            "bias_60m": "Neutral",
            "outlook": "Neutral",
            "state": "idle",
            "entry_ready": False,
            "reason": "No signal generated yet.",
        }
    context = derive_signal_context(
        row.signal,
        row.bias_5m,
        row.bias_30m,
        row.bias_60m,
        int(row.confidence),
    )
    return {
        "signal": row.signal,
        "confidence": int(row.confidence),
        "support": float(row.support) if row.support is not None else None,
        "resistance": float(row.resistance) if row.resistance is not None else None,
        "bias_5m": row.bias_5m,
        "bias_30m": row.bias_30m,
        "bias_60m": row.bias_60m,
        "outlook": context["outlook"],
        "state": context["state"],
        "entry_ready": context["entry_ready"],
        "reason": row.reason,
    }


def summary_payload_from_cache(row: Any) -> dict[str, Any]:
    if row is None:
        return {
            "insight": "Generating cached market insight...",
            "cached": False,
            "pending": True,
            "generated_at": None,
        }
    return {
        "insight": row.insight,
        "cached": True,
        "pending": False,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


def mark_payload_stale(
    payload: dict[str, Any],
    generated_at: datetime | None,
    *,
    now: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    updated = dict(payload)
    if generated_at is None:
        return updated

    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    if now - generated_at > max_age:
        updated["stale"] = True
    return updated
