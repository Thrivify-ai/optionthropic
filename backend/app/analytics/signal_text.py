from __future__ import annotations

TRADING_SIGNAL_REASON_MAX_LENGTH = 500


def fit_trading_signal_reason(reason: str | None) -> str:
    text = (reason or "").strip() or "Signal context unavailable."
    if len(text) <= TRADING_SIGNAL_REASON_MAX_LENGTH:
        return text
    return text[: TRADING_SIGNAL_REASON_MAX_LENGTH - 3].rstrip() + "..."
