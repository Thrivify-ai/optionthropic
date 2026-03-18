"""
Explanation Engine — convert technical signals into simple language.

Does not modify any existing logic. Pure functions only.
"""

from __future__ import annotations


def explain_signal(quick_signal: str, swing_signal: str) -> str:
    """
    Combine quick + swing signals into a simple explanation.
    Args:
        quick_signal: "Buy CE" | "Buy PE" | "Wait"
        swing_signal: "Buy CE" | "Buy PE" | "Wait"
    """
    q = (quick_signal or "Wait").strip()
    s = (swing_signal or "Wait").strip()

    if q == "Buy CE" and s == "Buy CE":
        return "Strong upward momentum with buyers dominating. Likely upward move."
    if q == "Buy PE" and s == "Buy PE":
        return "Selling pressure increasing with downward momentum. Market may fall."
    if q == "Buy CE" and s == "Wait":
        return "Short-term bullish burst. Watch for follow-through."
    if q == "Buy CE" and s == "Buy PE":
        return "Quick bounce up but larger trend is down. Cautious."
    if q == "Buy PE" and s == "Wait":
        return "Short-term bearish move. Monitor for continuation."
    if q == "Buy PE" and s == "Buy CE":
        return "Quick dip but trend is up. Could be a pullback."
    if q == "Wait" and s == "Buy CE":
        return "Short-term unclear but trend is upward."
    if q == "Wait" and s == "Buy PE":
        return "Short-term unclear but trend is downward."
    if q == "Wait" and s == "Wait":
        return "Market is sideways with no clear direction. Better to wait."
    return "No clear signal."


def explain_commodity_signal(quick_signal: str, long_signal: str) -> str:
    """
    Combine quick + long signals for commodities into a simple explanation.
    Args:
        quick_signal: "LONG" | "SHORT" | "WAIT"
        long_signal: "LONG" | "SHORT" | "WAIT"
    """
    q = (quick_signal or "WAIT").strip()
    s = (long_signal or "WAIT").strip()

    if q == "LONG" and s == "LONG":
        return "Strong upward momentum with trend aligned. Bullish bias."
    if q == "SHORT" and s == "SHORT":
        return "Selling pressure with downtrend. Bearish bias."
    if q == "LONG" and s == "WAIT":
        return "Short-term bullish burst. Watch for follow-through."
    if q == "LONG" and s == "SHORT":
        return "Quick bounce up but larger trend is down. Cautious."
    if q == "SHORT" and s == "WAIT":
        return "Short-term bearish move. Monitor for continuation."
    if q == "SHORT" and s == "LONG":
        return "Quick dip but trend is up. Could be a pullback."
    if q == "WAIT" and s == "LONG":
        return "Short-term unclear but trend is upward."
    if q == "WAIT" and s == "SHORT":
        return "Short-term unclear but trend is downward."
    if q == "WAIT" and s == "WAIT":
        return "Market is sideways with no clear direction. Better to wait."
    return "No clear signal."
