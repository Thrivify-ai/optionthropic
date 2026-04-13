"""
Long-signal specific hold / exit policy.

The main engine's entry logic is intentionally conservative, but once a trade
is active we want to manage it with finish-bias and structure-aware rules
instead of collapsing back into plain WAIT noise.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.main_signal_logic import FeatureView
from app.analytics.main_signal_runtime import LongSignalContext
from app.analytics.signal_engine import Bias
from app.analytics.trade_manager import OpenTradeState, points_for_direction


@dataclass(frozen=True)
class MainTradeManagementPlan:
    base_signal_override: str | None = None
    hard_exit: bool = False
    hard_exit_reason: str | None = None


def _price_above(level: float | None, price: float | None, *, buffer_pct: float = 0.0004) -> bool:
    if level is None or price is None:
        return False
    return float(price) >= float(level) * (1.0 + buffer_pct)


def _price_below(level: float | None, price: float | None, *, buffer_pct: float = 0.0004) -> bool:
    if level is None or price is None:
        return False
    return float(price) <= float(level) * (1.0 - buffer_pct)


def derive_main_trade_management_plan(
    *,
    open_trade: OpenTradeState | None,
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    long_context: LongSignalContext | None,
    outlook: Bias,
    confidence: int,
    current_price: float | None,
) -> MainTradeManagementPlan:
    if open_trade is None or current_price is None:
        return MainTradeManagementPlan()

    f5, f30, f60 = current_features
    if any(feature.trap_warning_flag for feature in current_features):
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="Higher-timeframe trap risk is confirmed. Exit the active trade.",
        )

    current_points = points_for_direction(open_trade.direction, open_trade.entry_price, current_price)
    price = float(current_price)
    vwap = long_context.session_vwap if long_context is not None else None
    opening_high = long_context.opening_range_high if long_context is not None else None
    opening_low = long_context.opening_range_low if long_context is not None else None
    prev_close = long_context.previous_day_close if long_context is not None else None
    prev_high = long_context.previous_day_high if long_context is not None else None
    prev_low = long_context.previous_day_low if long_context is not None else None

    if open_trade.direction == "CE":
        if outlook == Bias.BEARISH:
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="Higher-timeframe finish bias has flipped bearish.",
            )
        if (
            long_context is not None
            and long_context.breadth_available
            and int(long_context.breadth_score or 0) <= -25
            and confidence < 72
        ):
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="Internal breadth has flipped against the bullish trade.",
            )
        structural_break = (
            (vwap is not None and _price_below(vwap, price))
            and (
                f30.breakdown_flag
                or _price_below(opening_low, price)
                or _price_below(prev_low, price)
                or _price_below(prev_close, price)
            )
        )
        if structural_break:
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="Bullish structure broke below session support and VWAP.",
            )

        if (
            current_points is not None
            and current_points >= open_trade.success_threshold_points * 0.5
            and outlook != Bias.BULLISH
            and (
                (vwap is not None and _price_below(vwap, price))
                or _price_below(opening_low, price)
                or _price_below(prev_close, price)
            )
        ):
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="Bullish finish bias is fading after partial gains. Locking the trade.",
            )

        if (
            open_trade.max_favorable_points >= open_trade.success_threshold_points
            and current_points is not None
            and current_points < open_trade.max_favorable_points * 0.65
            and confidence < 72
        ):
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="More than half of the long trade's gains have been given back.",
            )

        if long_context is not None and long_context.event_profile in {"event", "event_expiry"}:
            if (
                long_context.session_bucket == "CLOSING"
                and current_points is not None
                and current_points > max(8.0, open_trade.success_threshold_points * 0.5)
                and confidence < 72
            ):
                return MainTradeManagementPlan(
                    hard_exit=True,
                    hard_exit_reason="Late-session event risk is elevated. Lock the remaining long gains.",
                )

        if outlook == Bias.BULLISH:
            return MainTradeManagementPlan(base_signal_override="Buy CE")

        if not _price_below(vwap, price) and not f30.breakdown_flag:
            if not _price_below(opening_low, price) and not _price_below(prev_close, price):
                return MainTradeManagementPlan(base_signal_override="Buy CE")

        return MainTradeManagementPlan()

    if outlook == Bias.BULLISH:
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="Higher-timeframe finish bias has flipped bullish.",
        )
    if (
        long_context is not None
        and long_context.breadth_available
        and int(long_context.breadth_score or 0) >= 25
        and confidence < 72
    ):
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="Internal breadth has flipped against the bearish trade.",
        )

    structural_break = (
        (vwap is not None and _price_above(vwap, price))
        and (
            f30.breakout_flag
            or _price_above(opening_high, price)
            or _price_above(prev_high, price)
            or _price_above(prev_close, price)
        )
    )
    if structural_break:
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="Bearish structure broke above session resistance and VWAP.",
        )

    if (
        current_points is not None
        and current_points >= open_trade.success_threshold_points * 0.5
        and outlook != Bias.BEARISH
        and (
            (vwap is not None and _price_above(vwap, price))
            or _price_above(opening_high, price)
            or _price_above(prev_close, price)
        )
    ):
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="Bearish finish bias is fading after partial gains. Locking the trade.",
        )

    if (
        open_trade.max_favorable_points >= open_trade.success_threshold_points
        and current_points is not None
        and current_points < open_trade.max_favorable_points * 0.65
        and confidence < 72
    ):
        return MainTradeManagementPlan(
            hard_exit=True,
            hard_exit_reason="More than half of the short trade's gains have been given back.",
        )

    if long_context is not None and long_context.event_profile in {"event", "event_expiry"}:
        if (
            long_context.session_bucket == "CLOSING"
            and current_points is not None
            and current_points > max(8.0, open_trade.success_threshold_points * 0.5)
            and confidence < 72
        ):
            return MainTradeManagementPlan(
                hard_exit=True,
                hard_exit_reason="Late-session event risk is elevated. Lock the remaining short gains.",
            )

    if outlook == Bias.BEARISH:
        return MainTradeManagementPlan(base_signal_override="Buy PE")

    if not _price_above(vwap, price) and not f30.breakout_flag:
        if not _price_above(opening_high, price) and not _price_above(prev_close, price):
            return MainTradeManagementPlan(base_signal_override="Buy PE")

    return MainTradeManagementPlan()
