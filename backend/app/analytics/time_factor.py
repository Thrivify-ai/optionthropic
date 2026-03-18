"""
Time-factor analytics for NSE intraday key windows.

Indian market (IST) key times where the system often moves in a direction:
- 10:30–10:55 AM — Opening range / first directional move
- 12:30 PM      — Pre-lunch / midday (narrow window)
- 1:20 PM       — Post-lunch resumption
- 2:55 PM       — Pre-close / closing hour momentum

We detect when current time (IST) is in one of these windows and combine
with live options-derived bias for alerts and the Time Factor card.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr

# IST = UTC+5:30
IST_OFFSET = timedelta(hours=5, minutes=30)


def _now_ist() -> tuple[int, int]:
    """Current time in IST as (hour, minute)."""
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + IST_OFFSET
    return ist_now.hour, ist_now.minute


def _minutes_since_midnight(h: int, m: int) -> int:
    return h * 60 + m


# Key windows: (start_min, end_min, label). Market 9:15–15:30 IST.
TIME_WINDOWS = [
    (10 * 60 + 30, 10 * 60 + 55, "10:30–10:55 AM", "Opening range / first move"),
    (12 * 60 + 25, 12 * 60 + 35, "12:30 PM", "Pre-lunch / midday"),
    (13 * 60 + 15, 13 * 60 + 25, "1:20 PM", "Post-lunch resumption"),
    (14 * 60 + 50, 15 * 60 + 5,  "2:55 PM", "Pre-close / closing hour"),
]


def get_current_window() -> dict[str, Any] | None:
    """
    Return the current IST time window if we're inside one, else None.
    """
    h, m = _now_ist()
    now_m = _minutes_since_midnight(h, m)

    for start_m, end_m, label, description in TIME_WINDOWS:
        if start_m <= now_m <= end_m:
            return {
                "id": label.replace(" ", "_").replace("–", "_"),
                "label": label,
                "description": description,
                "start": f"{start_m // 60}:{start_m % 60:02d}",
                "end": f"{end_m // 60}:{end_m % 60:02d}",
            }
    return None


def get_ist_now_iso() -> str:
    """Current IST time as ISO string for display."""
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + IST_OFFSET
    return ist_now.strftime("%H:%M IST")


async def get_time_factor_bias(session: AsyncSession, symbol: str) -> str:
    """
    Derive BULLISH / BEARISH / NEUTRAL from options (PCR + gamma/max pain).
    Used for time-factor card and TIME_FACTOR alerts.
    """
    score = 0
    try:
        pcr_data = await compute_pcr(session, symbol)
        sent = (pcr_data.get("sentiment") or "NEUTRAL").upper()
        if sent == "BULLISH":
            score += 1
        elif sent == "BEARISH":
            score -= 1
    except Exception:
        pass

    try:
        gw = await compute_gamma_walls(session, symbol)
        spot = gw.get("underlying_price")
        call_w = gw.get("call_wall")
        put_w = gw.get("put_wall")
        if spot and call_w and put_w and (call_w - put_w) != 0:
            pos = (spot - put_w) / (call_w - put_w)
            if pos > 0.6:
                score += 1
            elif pos < 0.4:
                score -= 1
    except Exception:
        pass

    try:
        mp_data = await compute_max_pain(session, symbol)
        spot = mp_data.get("underlying_price")
        mp = mp_data.get("max_pain_strike")
        if spot and mp:
            if mp > spot * 1.005:
                score += 1
            elif mp < spot * 0.995:
                score -= 1
    except Exception:
        pass

    if score >= 1:
        return "BULLISH"
    if score <= -1:
        return "BEARISH"
    return "NEUTRAL"


async def get_time_factor_signal(session: AsyncSession, symbol: str = "NIFTY") -> dict[str, Any]:
    """
    Combined time-factor signal for the dashboard card and API.
    Returns ist_now, window (or null), bias, and a short message.
    """
    window = get_current_window()
    ist_now = get_ist_now_iso()
    bias = await get_time_factor_bias(session, symbol)

    if not window:
        return {
            "ist_now": ist_now,
            "window": None,
            "bias": bias,
            "message": "No key time window — next: 10:30 AM, 12:30 PM, 1:20 PM, 2:55 PM IST",
            "in_window": False,
        }

    direction = bias.lower().capitalize()
    return {
        "ist_now": ist_now,
        "window": window,
        "bias": bias,
        "message": f"{window['label']} — {direction} bias from options buildup",
        "in_window": True,
        "symbol": symbol,
    }
