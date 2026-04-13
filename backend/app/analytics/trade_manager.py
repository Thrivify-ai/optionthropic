"""
Shared managed-trade helpers for entry / hold / exit behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.services.runtime_cache import runtime_cache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.managed_signal_trade import ManagedSignalTrade

ENTRY_SIGNALS = {"Buy CE", "Buy PE", "LONG", "SHORT"}
HOLD_SIGNAL_MAP = {
    "Buy CE": "Hold CE",
    "Buy PE": "Hold PE",
    "LONG": "HOLD LONG",
    "SHORT": "HOLD SHORT",
}
EXIT_SIGNAL_MAP = {
    "Buy CE": "Exit CE",
    "Buy PE": "Exit PE",
    "LONG": "EXIT LONG",
    "SHORT": "EXIT SHORT",
}
EXIT_CONFIDENCE_FLOOR = {
    "QUICK": 68,
    "MAIN": 65,
    "COMMODITY_QUICK": 64,
    "COMMODITY_LONG": 65,
}
ENTRY_CONFIDENCE_FLOOR = {
    "QUICK": 82,
    "MAIN": 80,
    "COMMODITY_QUICK": 78,
    "COMMODITY_LONG": 80,
}
REENTRY_LOCKOUT_SECONDS = {
    "QUICK": 120,
    "MAIN": 420,
    "COMMODITY_QUICK": 180,
    "COMMODITY_LONG": 600,
}
OPPOSITE_EXIT_EXTRA_CONFIDENCE = {
    "QUICK": 6,
    "MAIN": 4,
    "COMMODITY_QUICK": 5,
    "COMMODITY_LONG": 4,
}
OPPOSITE_EXIT_MIN_HOLD_CYCLES = {
    "QUICK": 2,
    "MAIN": 1,
    "COMMODITY_QUICK": 2,
    "COMMODITY_LONG": 1,
}
ADAPTIVE_ENTRY_LOOKBACK_DAYS = 14
ADAPTIVE_ENTRY_MIN_CLOSED_TRADES = {
    "QUICK": 24,
    "MAIN": 12,
    "COMMODITY_QUICK": 20,
    "COMMODITY_LONG": 10,
}
ADAPTIVE_ENTRY_FLOOR_CACHE_TTL_SECONDS = 180
SUCCESS_THRESHOLDS = {
    "QUICK": {
        "NIFTY": 10.0,
        "BANKNIFTY": 25.0,
        "SENSEX": 30.0,
    },
    "MAIN": {
        "NIFTY": 20.0,
        "BANKNIFTY": 45.0,
        "SENSEX": 60.0,
    },
    "COMMODITY_QUICK": {
        "CRUDEOIL": 20.0,
        "NATGAS": 5.0,
        "GOLD": 70.0,
        "SILVER": 80.0,
    },
    "COMMODITY_LONG": {
        "CRUDEOIL": 45.0,
        "NATGAS": 10.0,
        "GOLD": 150.0,
        "SILVER": 180.0,
    },
}
STOP_THRESHOLDS = {
    "QUICK": {
        "NIFTY": 8.0,
        "BANKNIFTY": 18.0,
        "SENSEX": 22.0,
    },
    "MAIN": {
        "NIFTY": 14.0,
        "BANKNIFTY": 30.0,
        "SENSEX": 40.0,
    },
    "COMMODITY_QUICK": {
        "CRUDEOIL": 14.0,
        "NATGAS": 3.0,
        "GOLD": 45.0,
        "SILVER": 55.0,
    },
    "COMMODITY_LONG": {
        "CRUDEOIL": 28.0,
        "NATGAS": 7.0,
        "GOLD": 90.0,
        "SILVER": 110.0,
    },
}


@dataclass
class OpenTradeState:
    id: int | None
    engine: str
    symbol: str
    direction: str
    entry_signal: str
    entry_price: float
    entry_time: datetime
    entry_confidence: int
    success_threshold_points: float
    stop_points: float
    hold_cycles: int = 0
    max_favorable_points: float = 0.0
    max_adverse_points: float = 0.0


@dataclass
class ManagedTradeDecision:
    public_signal: str
    trade_state: str
    action: str
    direction: str | None
    entry_price: float | None
    current_price: float | None
    current_points: float | None
    success_threshold_points: float
    stop_points: float
    hold_cycles: int
    max_favorable_points: float | None
    max_adverse_points: float | None
    management_reason: str
    exit_reason: str | None = None


def direction_for_signal(signal: str | None) -> str | None:
    if signal is None:
        return None
    signal = signal.strip()
    normalized = signal.upper()
    if signal.endswith("CE"):
        return "CE"
    if signal.endswith("PE"):
        return "PE"
    if normalized in {"LONG", "HOLD LONG", "EXIT LONG"}:
        return "LONG"
    if normalized in {"SHORT", "HOLD SHORT", "EXIT SHORT"}:
        # Keep within the existing VARCHAR(4) direction column.
        return "SHRT"
    return None


def points_for_direction(direction: str | None, entry_price: float | None, current_price: float | None) -> float | None:
    if direction not in {"CE", "PE", "LONG", "SHRT"} or entry_price is None or current_price is None:
        return None
    if direction in {"CE", "LONG"}:
        return round(float(current_price) - float(entry_price), 2)
    return round(float(entry_price) - float(current_price), 2)


def hold_signal_for_entry(entry_signal: str) -> str:
    return HOLD_SIGNAL_MAP.get(entry_signal, "Wait")


def exit_signal_for_entry(entry_signal: str) -> str:
    return EXIT_SIGNAL_MAP.get(entry_signal, "Wait")


def success_threshold_points(engine: str, symbol: str) -> float:
    return SUCCESS_THRESHOLDS.get(engine.upper(), {}).get(symbol.upper(), 10.0)


def stop_threshold_points(engine: str, symbol: str) -> float:
    return STOP_THRESHOLDS.get(engine.upper(), {}).get(symbol.upper(), 8.0)


def entry_confidence_floor(engine: str) -> int:
    return ENTRY_CONFIDENCE_FLOOR.get(engine.upper(), 75)


def reentry_lockout_seconds(engine: str) -> int:
    return REENTRY_LOCKOUT_SECONDS.get(engine.upper(), 180)


async def _acquire_managed_trade_lock(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
) -> None:
    """
    Serialize one managed-trade lifecycle per engine/symbol across API polls.
    Postgres keeps this transaction-level lock until the request/collector commits.
    """
    from sqlalchemy import text

    lock_key = f"managed-trade:{engine.upper()}:{symbol.upper()}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )


def _adaptive_entry_floor_cache_key(engine: str, symbol: str) -> str:
    return f"managed-entry-floor:{engine.upper()}:{symbol.upper()}"


async def adaptive_entry_confidence_floor(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    now_utc: datetime,
) -> int:
    """
    Adaptive entry floor calibrated from recent managed outcomes.
    We only tighten floors; never loosen below the static baseline.
    """
    base_floor = entry_confidence_floor(engine)
    cache_key = _adaptive_entry_floor_cache_key(engine, symbol)
    cached = await runtime_cache.get_json(cache_key)
    if isinstance(cached, dict):
        cached_floor = cached.get("floor")
        if isinstance(cached_floor, int):
            return max(base_floor, min(96, int(cached_floor)))

    from sqlalchemy import case, func, select
    from app.models.managed_signal_trade import ManagedSignalTrade

    engine_key = engine.upper()
    symbol_key = symbol.upper()
    cutoff = now_utc - timedelta(days=ADAPTIVE_ENTRY_LOOKBACK_DAYS)
    min_samples = ADAPTIVE_ENTRY_MIN_CLOSED_TRADES.get(engine_key, 16)

    row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.sum(case((ManagedSignalTrade.result_label == "Won", 1), else_=0)).label("won"),
                func.sum(case((ManagedSignalTrade.result_label == "Lost", 1), else_=0)).label("lost"),
                func.sum(func.coalesce(ManagedSignalTrade.realized_points, 0)).label("net_points"),
            )
            .where(
                ManagedSignalTrade.engine == engine_key,
                ManagedSignalTrade.symbol == symbol_key,
                ManagedSignalTrade.status == "CLOSED",
                ManagedSignalTrade.entry_time >= cutoff,
            )
        )
    ).first()

    total = int(getattr(row, "total", 0) or 0) if row is not None else 0
    won = int(getattr(row, "won", 0) or 0) if row is not None else 0
    lost = int(getattr(row, "lost", 0) or 0) if row is not None else 0
    net_points = float(getattr(row, "net_points", 0.0) or 0.0) if row is not None else 0.0

    floor = int(base_floor)
    decided = won + lost
    win_rate = (won / decided) if decided > 0 else None

    if total >= min_samples:
        if win_rate is not None:
            if win_rate < 0.35:
                floor += 8
            elif win_rate < 0.45:
                floor += 4
        if net_points < 0:
            floor += 2

    floor = max(base_floor, min(96, int(floor)))
    await runtime_cache.set_json(
        cache_key,
        {"floor": floor, "samples": total, "decided": decided},
        ttl_seconds=ADAPTIVE_ENTRY_FLOOR_CACHE_TTL_SECONDS,
    )
    return floor


def result_label_from_points(points: float | None, *, success_threshold: float) -> str:
    if points is None:
        return "Unknown"
    if points >= success_threshold:
        return "Won"
    if points >= 0:
        return "Scratch"
    return "Lost"


def trade_state_from_row(row: ManagedSignalTrade | None) -> OpenTradeState | None:
    if row is None:
        return None
    return OpenTradeState(
        id=int(row.id),
        engine=row.engine,
        symbol=row.symbol,
        direction=row.direction,
        entry_signal=row.entry_signal,
        entry_price=float(row.entry_price),
        entry_time=row.entry_time,
        entry_confidence=int(row.entry_confidence),
        success_threshold_points=float(row.success_threshold_points),
        stop_points=float(row.stop_points),
        hold_cycles=int(row.hold_cycles or 0),
        max_favorable_points=float(row.max_favorable_points or 0),
        max_adverse_points=float(row.max_adverse_points or 0),
    )


def serialize_trade_summary(row: ManagedSignalTrade | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "status": row.status.lower(),
        "direction": row.direction,
        "entry_signal": row.entry_signal,
        "latest_signal": row.latest_signal,
        "signal_version": row.signal_version,
        "entry_price": float(row.entry_price) if row.entry_price is not None else None,
        "latest_price": float(row.latest_price) if row.latest_price is not None else None,
        "latest_points": float(row.latest_points) if row.latest_points is not None else None,
        "success_threshold_points": float(row.success_threshold_points),
        "stop_points": float(row.stop_points),
        "hold_cycles": int(row.hold_cycles or 0),
        "max_favorable_points": float(row.max_favorable_points or 0),
        "max_adverse_points": float(row.max_adverse_points or 0),
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "exit_time": row.exit_time.isoformat() if row.exit_time else None,
        "result_label": row.result_label,
    }


def derive_managed_trade_decision(
    *,
    engine: str,
    symbol: str,
    previous_trade: OpenTradeState | None,
    base_signal: str,
    confidence: int,
    current_price: float | None,
    reason: str,
    hard_exit: bool = False,
    hard_exit_reason: str | None = None,
    success_threshold_override: float | None = None,
    stop_points_override: float | None = None,
    reentry_block_reason: str | None = None,
    entry_gate_reason: str | None = None,
    minimum_entry_confidence_override: int | None = None,
) -> ManagedTradeDecision:
    threshold = float(success_threshold_override) if success_threshold_override is not None else success_threshold_points(engine, symbol)
    stop = float(stop_points_override) if stop_points_override is not None else stop_threshold_points(engine, symbol)
    direction = direction_for_signal(base_signal)
    exit_floor = EXIT_CONFIDENCE_FLOOR.get(engine.upper(), 65)

    if previous_trade is None:
        if base_signal in ENTRY_SIGNALS and current_price is not None:
            minimum_entry_confidence = (
                int(minimum_entry_confidence_override)
                if minimum_entry_confidence_override is not None
                else entry_confidence_floor(engine)
            )
            if confidence < minimum_entry_confidence:
                floor_note = (
                    " (calibrated floor)"
                    if minimum_entry_confidence_override is not None
                    and int(minimum_entry_confidence_override) > entry_confidence_floor(engine)
                    else ""
                )
                return ManagedTradeDecision(
                    public_signal="Wait",
                    trade_state="idle",
                    action="wait",
                    direction=direction,
                    entry_price=None,
                    current_price=current_price,
                    current_points=None,
                    success_threshold_points=threshold,
                    stop_points=stop,
                    hold_cycles=0,
                    max_favorable_points=None,
                    max_adverse_points=None,
                    management_reason=(
                        f"Entry blocked: confidence {confidence}% is below the "
                        f"{minimum_entry_confidence}% minimum{floor_note}."
                    ),
                )
            if reentry_block_reason:
                return ManagedTradeDecision(
                    public_signal="Wait",
                    trade_state="idle",
                    action="wait",
                    direction=direction,
                    entry_price=None,
                    current_price=current_price,
                    current_points=None,
                    success_threshold_points=threshold,
                    stop_points=stop,
                    hold_cycles=0,
                    max_favorable_points=None,
                    max_adverse_points=None,
                    management_reason=reentry_block_reason,
                )
            if entry_gate_reason:
                return ManagedTradeDecision(
                    public_signal="Wait",
                    trade_state="idle",
                    action="wait",
                    direction=direction,
                    entry_price=None,
                    current_price=current_price,
                    current_points=None,
                    success_threshold_points=threshold,
                    stop_points=stop,
                    hold_cycles=0,
                    max_favorable_points=None,
                    max_adverse_points=None,
                    management_reason=entry_gate_reason,
                )
            return ManagedTradeDecision(
                public_signal=base_signal,
                trade_state="entry",
                action="entry",
                direction=direction,
                entry_price=float(current_price),
                current_price=float(current_price),
                current_points=0.0,
                success_threshold_points=threshold,
                stop_points=stop,
                hold_cycles=0,
                max_favorable_points=0.0,
                max_adverse_points=0.0,
                management_reason=reason,
            )
        return ManagedTradeDecision(
            public_signal="Wait",
            trade_state="idle",
            action="wait",
            direction=None,
            entry_price=None,
            current_price=current_price,
            current_points=None,
            success_threshold_points=threshold,
            stop_points=stop,
            hold_cycles=0,
            max_favorable_points=None,
            max_adverse_points=None,
            management_reason=reason,
        )

    current_points = points_for_direction(previous_trade.direction, previous_trade.entry_price, current_price)
    max_favorable = max(previous_trade.max_favorable_points, current_points or previous_trade.max_favorable_points)
    max_adverse = min(previous_trade.max_adverse_points, current_points or previous_trade.max_adverse_points)
    same_direction_signal = direction == previous_trade.direction and base_signal in ENTRY_SIGNALS
    opposite_entry = direction is not None and direction != previous_trade.direction and base_signal in ENTRY_SIGNALS

    if hard_exit:
        exit_reason = hard_exit_reason or "Structure invalidated with high conviction."
        return ManagedTradeDecision(
            public_signal=exit_signal_for_entry(previous_trade.entry_signal),
            trade_state="exit",
            action="exit",
            direction=previous_trade.direction,
            entry_price=previous_trade.entry_price,
            current_price=current_price,
            current_points=current_points,
            success_threshold_points=previous_trade.success_threshold_points,
            stop_points=previous_trade.stop_points,
            hold_cycles=previous_trade.hold_cycles,
            max_favorable_points=max_favorable,
            max_adverse_points=max_adverse,
            management_reason=exit_reason,
            exit_reason=exit_reason,
        )

    if current_points is not None and current_points <= -previous_trade.stop_points:
        exit_reason = f"Stop triggered after {current_points:.0f} points against the trade."
        return ManagedTradeDecision(
            public_signal=exit_signal_for_entry(previous_trade.entry_signal),
            trade_state="exit",
            action="exit",
            direction=previous_trade.direction,
            entry_price=previous_trade.entry_price,
            current_price=current_price,
            current_points=current_points,
            success_threshold_points=previous_trade.success_threshold_points,
            stop_points=previous_trade.stop_points,
            hold_cycles=previous_trade.hold_cycles,
            max_favorable_points=max_favorable,
            max_adverse_points=max_adverse,
            management_reason=exit_reason,
            exit_reason=exit_reason,
        )

    opposite_exit_floor = exit_floor + OPPOSITE_EXIT_EXTRA_CONFIDENCE.get(engine.upper(), 4)
    opposite_min_hold_cycles = OPPOSITE_EXIT_MIN_HOLD_CYCLES.get(engine.upper(), 1)
    opposite_exit_allowed = True
    opposite_hold_reason = None
    if opposite_entry and confidence >= opposite_exit_floor:
        if (
            previous_trade.hold_cycles < opposite_min_hold_cycles
            and (
                current_points is None
                or current_points > -previous_trade.stop_points * 0.5
            )
        ):
            opposite_exit_allowed = False
            opposite_hold_reason = (
                f"Opposite signal reached {confidence}% but needs one more cycle before exit confirmation."
            )
    if opposite_entry and confidence >= opposite_exit_floor and opposite_exit_allowed:
        exit_reason = (
            f"Opposite move has high conviction ({confidence}%) and persistence - exit the current trade."
        )
        return ManagedTradeDecision(
            public_signal=exit_signal_for_entry(previous_trade.entry_signal),
            trade_state="exit",
            action="exit",
            direction=previous_trade.direction,
            entry_price=previous_trade.entry_price,
            current_price=current_price,
            current_points=current_points,
            success_threshold_points=previous_trade.success_threshold_points,
            stop_points=previous_trade.stop_points,
            hold_cycles=previous_trade.hold_cycles,
            max_favorable_points=max_favorable,
            max_adverse_points=max_adverse,
            management_reason=exit_reason,
            exit_reason=exit_reason,
        )

    partial_profit_trigger = previous_trade.success_threshold_points * 0.7
    if (
        current_points is not None
        and current_points >= partial_profit_trigger
        and not same_direction_signal
        and confidence < exit_floor
    ):
        exit_reason = (
            f"Protected partial profit after {current_points:.0f} points as follow-through weakened."
        )
        return ManagedTradeDecision(
            public_signal=exit_signal_for_entry(previous_trade.entry_signal),
            trade_state="exit",
            action="exit",
            direction=previous_trade.direction,
            entry_price=previous_trade.entry_price,
            current_price=current_price,
            current_points=current_points,
            success_threshold_points=previous_trade.success_threshold_points,
            stop_points=previous_trade.stop_points,
            hold_cycles=previous_trade.hold_cycles,
            max_favorable_points=max_favorable,
            max_adverse_points=max_adverse,
            management_reason=exit_reason,
            exit_reason=exit_reason,
        )

    if current_points is not None and max_favorable >= partial_profit_trigger:
        giveback = max_favorable - current_points
        allowed_giveback = max(
            previous_trade.success_threshold_points * 0.35,
            previous_trade.stop_points * 0.85,
        )
        if current_points > 0 and giveback >= allowed_giveback:
            exit_reason = (
                f"Trailing protection hit after giving back {giveback:.0f} points from peak."
            )
            return ManagedTradeDecision(
                public_signal=exit_signal_for_entry(previous_trade.entry_signal),
                trade_state="exit",
                action="exit",
                direction=previous_trade.direction,
                entry_price=previous_trade.entry_price,
                current_price=current_price,
                current_points=current_points,
                success_threshold_points=previous_trade.success_threshold_points,
                stop_points=previous_trade.stop_points,
                hold_cycles=previous_trade.hold_cycles,
                max_favorable_points=max_favorable,
                max_adverse_points=max_adverse,
                management_reason=exit_reason,
                exit_reason=exit_reason,
            )

    if (
        current_points is not None
        and current_points >= previous_trade.success_threshold_points
        and not same_direction_signal
        and confidence >= exit_floor
    ):
        exit_reason = (
            f"Booked gains after capturing {current_points:.0f} points with confirmation fading."
        )
        return ManagedTradeDecision(
            public_signal=exit_signal_for_entry(previous_trade.entry_signal),
            trade_state="exit",
            action="exit",
            direction=previous_trade.direction,
            entry_price=previous_trade.entry_price,
            current_price=current_price,
            current_points=current_points,
            success_threshold_points=previous_trade.success_threshold_points,
            stop_points=previous_trade.stop_points,
            hold_cycles=previous_trade.hold_cycles,
            max_favorable_points=max_favorable,
            max_adverse_points=max_adverse,
            management_reason=exit_reason,
            exit_reason=exit_reason,
        )

    hold_reason = opposite_hold_reason or reason
    if not same_direction_signal and opposite_hold_reason is None:
        hold_reason = (
            f"{reason} Hold the trade unless invalidation appears or the move reaches +"
            f"{previous_trade.success_threshold_points:.0f} points."
        )

    return ManagedTradeDecision(
        public_signal=hold_signal_for_entry(previous_trade.entry_signal),
        trade_state="hold",
        action="hold",
        direction=previous_trade.direction,
        entry_price=previous_trade.entry_price,
        current_price=current_price,
        current_points=current_points,
        success_threshold_points=previous_trade.success_threshold_points,
        stop_points=previous_trade.stop_points,
        hold_cycles=previous_trade.hold_cycles + 1,
        max_favorable_points=max_favorable,
        max_adverse_points=max_adverse,
        management_reason=hold_reason,
    )


async def get_open_trade_row(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
) -> ManagedSignalTrade | None:
    from sqlalchemy import desc, select
    from app.models.managed_signal_trade import ManagedSignalTrade

    return (
        await session.execute(
            select(ManagedSignalTrade)
            .where(
                ManagedSignalTrade.engine == engine.upper(),
                ManagedSignalTrade.symbol == symbol.upper(),
                ManagedSignalTrade.status == "OPEN",
            )
            .order_by(desc(ManagedSignalTrade.entry_time))
            .limit(1)
        )
    ).scalars().first()


async def get_latest_trade_row(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
) -> ManagedSignalTrade | None:
    from sqlalchemy import desc, select
    from app.models.managed_signal_trade import ManagedSignalTrade

    return (
        await session.execute(
            select(ManagedSignalTrade)
            .where(
                ManagedSignalTrade.engine == engine.upper(),
                ManagedSignalTrade.symbol == symbol.upper(),
            )
            .order_by(
                ManagedSignalTrade.status.asc(),
                desc(ManagedSignalTrade.updated_at),
                desc(ManagedSignalTrade.entry_time),
            )
            .limit(1)
        )
    ).scalars().first()


async def get_latest_closed_trade_row(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    direction: str,
) -> ManagedSignalTrade | None:
    from sqlalchemy import desc, select
    from app.models.managed_signal_trade import ManagedSignalTrade

    return (
        await session.execute(
            select(ManagedSignalTrade)
            .where(
                ManagedSignalTrade.engine == engine.upper(),
                ManagedSignalTrade.symbol == symbol.upper(),
                ManagedSignalTrade.status == "CLOSED",
                ManagedSignalTrade.direction == direction,
            )
            .order_by(
                desc(ManagedSignalTrade.exit_time),
                desc(ManagedSignalTrade.updated_at),
            )
            .limit(1)
        )
    ).scalars().first()


async def record_managed_trade_decision(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    confidence: int,
    now_utc: datetime,
    decision: ManagedTradeDecision,
    entry_reason: str,
    signal_version: str | None = None,
) -> ManagedSignalTrade | None:
    from app.models.managed_signal_trade import ManagedSignalTrade

    row = await get_open_trade_row(session, engine=engine, symbol=symbol)

    if decision.action == "entry":
        if row is None and decision.entry_price is not None and decision.direction is not None:
            row = ManagedSignalTrade(
                engine=engine.upper(),
                symbol=symbol.upper(),
                status="OPEN",
                direction=decision.direction,
                entry_signal=decision.public_signal,
                latest_signal=decision.public_signal,
                signal_version=signal_version,
                entry_confidence=int(confidence),
                latest_confidence=int(confidence),
                entry_price=round(float(decision.entry_price), 2),
                latest_price=round(float(decision.current_price), 2) if decision.current_price is not None else None,
                latest_points=round(float(decision.current_points or 0.0), 2),
                success_threshold_points=round(float(decision.success_threshold_points), 2),
                stop_points=round(float(decision.stop_points), 2),
                hold_cycles=int(decision.hold_cycles),
                max_favorable_points=round(float(decision.max_favorable_points or 0.0), 2),
                max_adverse_points=round(float(decision.max_adverse_points or 0.0), 2),
                entry_reason=entry_reason,
                latest_reason=decision.management_reason,
                entry_time=now_utc,
            )
            session.add(row)
            await session.flush()
        return row

    if row is None:
        return None

    row.latest_signal = decision.public_signal
    if signal_version:
        row.signal_version = signal_version
    row.latest_confidence = int(confidence)
    row.latest_reason = decision.management_reason
    row.latest_price = round(float(decision.current_price), 2) if decision.current_price is not None else None
    row.latest_points = round(float(decision.current_points), 2) if decision.current_points is not None else None
    row.hold_cycles = int(decision.hold_cycles)
    if decision.max_favorable_points is not None:
        row.max_favorable_points = round(float(decision.max_favorable_points), 2)
    if decision.max_adverse_points is not None:
        row.max_adverse_points = round(float(decision.max_adverse_points), 2)

    if decision.action == "exit":
        realized_points = round(float(decision.current_points or 0.0), 2)
        row.status = "CLOSED"
        row.exit_signal = decision.public_signal
        row.exit_confidence = int(confidence)
        row.exit_price = round(float(decision.current_price), 2) if decision.current_price is not None else None
        row.exit_reason = decision.exit_reason or decision.management_reason
        row.realized_points = realized_points
        row.result_label = result_label_from_points(
            realized_points,
            success_threshold=float(row.success_threshold_points),
        )
        row.exit_time = now_utc

    await session.flush()
    return row


async def apply_managed_trade_decision(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    base_signal: str,
    confidence: int,
    current_price: float | None,
    reason: str,
    now_utc: datetime,
    hard_exit: bool = False,
    hard_exit_reason: str | None = None,
    success_threshold_override: float | None = None,
    stop_points_override: float | None = None,
    signal_version: str | None = None,
    entry_gate_reason: str | None = None,
) -> tuple[ManagedTradeDecision, ManagedSignalTrade | None]:
    await _acquire_managed_trade_lock(session, engine=engine, symbol=symbol)

    open_row = await get_open_trade_row(session, engine=engine, symbol=symbol)
    previous_trade = trade_state_from_row(open_row)
    reentry_block_reason = None
    signal_direction = direction_for_signal(base_signal)
    minimum_entry_confidence_override = None
    if previous_trade is None and base_signal in ENTRY_SIGNALS and signal_direction is not None:
        minimum_entry_confidence_override = await adaptive_entry_confidence_floor(
            session,
            engine=engine,
            symbol=symbol,
            now_utc=now_utc,
        )
        latest_closed = await get_latest_closed_trade_row(
            session,
            engine=engine,
            symbol=symbol,
            direction=signal_direction,
        )
        if latest_closed is not None and latest_closed.exit_time is not None:
            cooldown = timedelta(seconds=reentry_lockout_seconds(engine))
            if now_utc < latest_closed.exit_time + cooldown:
                remaining = int(((latest_closed.exit_time + cooldown) - now_utc).total_seconds())
                reentry_block_reason = (
                    f"Re-entry lockout active for {signal_direction}: wait {max(1, remaining)}s "
                    f"before opening another trade in the same direction."
                )

    decision = derive_managed_trade_decision(
        engine=engine,
        symbol=symbol,
        previous_trade=previous_trade,
        base_signal=base_signal,
        confidence=int(confidence),
        current_price=current_price,
        reason=reason,
        hard_exit=hard_exit,
        hard_exit_reason=hard_exit_reason,
        success_threshold_override=success_threshold_override,
        stop_points_override=stop_points_override,
        reentry_block_reason=reentry_block_reason,
        entry_gate_reason=entry_gate_reason,
        minimum_entry_confidence_override=minimum_entry_confidence_override,
    )
    trade_row = await record_managed_trade_decision(
        session,
        engine=engine,
        symbol=symbol,
        confidence=int(confidence),
        now_utc=now_utc,
        decision=decision,
        entry_reason=reason,
        signal_version=signal_version,
    )
    return decision, trade_row
