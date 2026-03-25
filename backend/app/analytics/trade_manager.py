"""
Shared managed-trade helpers for entry / hold / exit behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.managed_signal_trade import ManagedSignalTrade

ENTRY_SIGNALS = {"Buy CE", "Buy PE"}
HOLD_SIGNAL_MAP = {
    "Buy CE": "Hold CE",
    "Buy PE": "Hold PE",
}
EXIT_SIGNAL_MAP = {
    "Buy CE": "Exit CE",
    "Buy PE": "Exit PE",
}
EXIT_CONFIDENCE_FLOOR = {
    "QUICK": 68,
    "MAIN": 65,
}
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
    if signal.endswith("CE"):
        return "CE"
    if signal.endswith("PE"):
        return "PE"
    return None


def points_for_direction(direction: str | None, entry_price: float | None, current_price: float | None) -> float | None:
    if direction not in {"CE", "PE"} or entry_price is None or current_price is None:
        return None
    if direction == "CE":
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
) -> ManagedTradeDecision:
    threshold = success_threshold_points(engine, symbol)
    stop = stop_threshold_points(engine, symbol)
    direction = direction_for_signal(base_signal)
    exit_floor = EXIT_CONFIDENCE_FLOOR.get(engine.upper(), 65)

    if previous_trade is None:
        if base_signal in ENTRY_SIGNALS and current_price is not None:
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

    if opposite_entry and confidence >= exit_floor:
        exit_reason = f"Opposite move has high conviction ({confidence}%) - exit the current trade."
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

    hold_reason = reason
    if not same_direction_signal:
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


async def record_managed_trade_decision(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    confidence: int,
    now_utc: datetime,
    decision: ManagedTradeDecision,
    entry_reason: str,
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
) -> tuple[ManagedTradeDecision, ManagedSignalTrade | None]:
    open_row = await get_open_trade_row(session, engine=engine, symbol=symbol)
    previous_trade = trade_state_from_row(open_row)
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
    )
    trade_row = await record_managed_trade_decision(
        session,
        engine=engine,
        symbol=symbol,
        confidence=int(confidence),
        now_utc=now_utc,
        decision=decision,
        entry_reason=reason,
    )
    return decision, trade_row
