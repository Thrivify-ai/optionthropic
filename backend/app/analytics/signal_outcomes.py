"""
Signal outcome persistence and calibration helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.signal_outcome import SignalOutcome

_ENGINE_HORIZONS = {
    "QUICK": (2, 3),
    "MAIN": (5, 10, 30),
}
_ALL_HORIZONS = (2, 3, 5, 10, 30)
_DEDUP_WINDOWS = {
    "QUICK": 90,
    "MAIN": 900,
}
_CONFIDENCE_BUCKETS = (
    (0, 49, "0-49"),
    (50, 59, "50-59"),
    (60, 69, "60-69"),
    (70, 79, "70-79"),
    (80, 89, "80-89"),
    (90, 100, "90-100"),
)


@dataclass
class CalibrationRow:
    engine: str
    confidence: int
    preferred_outcome: str


def classify_outcome(signal: str, entry_price: float | None, price_later: float | None) -> str:
    if not entry_price or price_later is None:
        return "Unknown"
    move = price_later - entry_price
    if signal == "Buy CE" and move > 0:
        return "Won"
    if signal == "Buy CE" and move < 0:
        return "Lost"
    if signal == "Buy PE" and move < 0:
        return "Won"
    if signal == "Buy PE" and move > 0:
        return "Lost"
    return "Unknown"


def confidence_bucket(confidence: int) -> str:
    for low, high, label in _CONFIDENCE_BUCKETS:
        if low <= confidence <= high:
            return label
    return "90-100" if confidence > 100 else "0-49"


def preferred_outcome_for_engine(engine: str, row: Any) -> str:
    engine = engine.upper()
    if engine == "QUICK":
        for field in ("outcome_2m", "outcome_3m"):
            value = getattr(row, field, None)
            if value and value != "Unknown":
                return value
        return "Unknown"

    for field in ("outcome_5m", "outcome_10m", "outcome_30m"):
        value = getattr(row, field, None)
        if value and value != "Unknown":
            return value
    return "Unknown"


def summarize_calibration(rows: list[CalibrationRow]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        bucket = confidence_bucket(int(row.confidence))
        key = (row.engine.upper(), bucket)
        summary = buckets.setdefault(
            key,
            {
                "engine": row.engine.upper(),
                "bucket": bucket,
                "total": 0,
                "won": 0,
                "lost": 0,
                "unknown": 0,
                "win_rate_pct": None,
            },
        )
        summary["total"] += 1
        if row.preferred_outcome == "Won":
            summary["won"] += 1
        elif row.preferred_outcome == "Lost":
            summary["lost"] += 1
        else:
            summary["unknown"] += 1

    ordered: list[dict[str, Any]] = []
    for engine in ("QUICK", "MAIN"):
        for _, _, bucket in _CONFIDENCE_BUCKETS:
            summary = buckets.get((engine, bucket))
            if summary is None:
                continue
            decided = summary["won"] + summary["lost"]
            summary["win_rate_pct"] = round(100 * summary["won"] / decided, 1) if decided > 0 else None
            ordered.append(summary)
    return ordered


async def price_at_time(session: AsyncSession, symbol: str, target: datetime) -> float | None:
    from sqlalchemy import select
    from app.models.chain_snapshot import ChainSnapshot

    window = timedelta(minutes=15)
    stmt = (
        select(ChainSnapshot.underlying_price, ChainSnapshot.timestamp)
        .where(
            ChainSnapshot.symbol == symbol,
            ChainSnapshot.timestamp >= target - window,
            ChainSnapshot.timestamp <= target + window,
        )
        .order_by(ChainSnapshot.timestamp.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None

    target_ts = target.timestamp()
    seen_ts = set()
    best_price = None
    best_diff = float("inf")
    for price, ts in rows:
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        diff = abs((ts or target).timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_price = price
    return float(best_price) if best_price is not None else None


async def record_signal_outcome_candidate(
    session: AsyncSession,
    *,
    engine: str,
    symbol: str,
    signal: str,
    confidence: int,
    entry_price: float,
    entry_time: datetime,
    reason: str | None = None,
    outlook: str | None = None,
    state: str | None = None,
) -> SignalOutcome:
    from sqlalchemy import desc, select
    from app.models.signal_outcome import SignalOutcome

    engine = engine.upper()
    dedupe_seconds = _DEDUP_WINDOWS.get(engine, 300)
    cutoff = entry_time - timedelta(seconds=dedupe_seconds)

    stmt = (
        select(SignalOutcome)
        .where(
            SignalOutcome.engine == engine,
            SignalOutcome.symbol == symbol,
            SignalOutcome.signal == signal,
            SignalOutcome.entry_time >= cutoff,
        )
        .order_by(desc(SignalOutcome.entry_time))
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        return existing

    row = SignalOutcome(
        engine=engine,
        symbol=symbol,
        signal=signal,
        confidence=int(confidence),
        outlook=outlook,
        state=state,
        entry_price=round(float(entry_price), 2),
        reason=reason,
        entry_time=entry_time,
    )
    session.add(row)
    await session.flush()
    return row


async def refresh_pending_signal_outcomes(
    session: AsyncSession,
    *,
    lookback_hours: int = 48,
    limit: int = 250,
) -> int:
    from sqlalchemy import select
    from app.models.signal_outcome import SignalOutcome

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=lookback_hours)
    rows = (
        await session.execute(
            select(SignalOutcome)
            .where(SignalOutcome.entry_time >= cutoff)
            .order_by(SignalOutcome.entry_time.asc())
            .limit(limit)
        )
    ).scalars().all()

    updated = 0
    for row in rows:
        row_updated = False
        for horizon in _ALL_HORIZONS:
            price_field = f"price_{horizon}m"
            move_field = f"move_{horizon}m"
            outcome_field = f"outcome_{horizon}m"

            if getattr(row, price_field) is not None or getattr(row, outcome_field) is not None:
                continue

            target = row.entry_time
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            target = target + timedelta(minutes=horizon)
            if now_utc < target:
                continue

            price_later = await price_at_time(session, row.symbol, target)
            if price_later is None:
                if now_utc >= target + timedelta(minutes=15):
                    setattr(row, outcome_field, "Unknown")
                    row_updated = True
                continue

            move = round(price_later - float(row.entry_price), 2)
            outcome = classify_outcome(row.signal, float(row.entry_price), price_later)
            setattr(row, price_field, round(price_later, 2))
            setattr(row, move_field, move)
            setattr(row, outcome_field, outcome)
            row_updated = True

        if row_updated:
            row.updated_at = now_utc
            updated += 1

    return updated


def serialize_outcome_row(row: SignalOutcome) -> dict[str, Any]:
    return {
        "id": row.id,
        "engine": row.engine,
        "symbol": row.symbol,
        "signal": row.signal,
        "confidence": int(row.confidence),
        "outlook": row.outlook,
        "state": row.state,
        "created_at": row.entry_time.isoformat() if row.entry_time else None,
        "price_at_signal": round(float(row.entry_price), 2) if row.entry_price is not None else None,
        "price_2m": round(float(row.price_2m), 2) if row.price_2m is not None else None,
        "price_3m": round(float(row.price_3m), 2) if row.price_3m is not None else None,
        "price_5m": round(float(row.price_5m), 2) if row.price_5m is not None else None,
        "price_10m": round(float(row.price_10m), 2) if row.price_10m is not None else None,
        "price_30m": round(float(row.price_30m), 2) if row.price_30m is not None else None,
        "move_2m": round(float(row.move_2m), 2) if row.move_2m is not None else None,
        "move_3m": round(float(row.move_3m), 2) if row.move_3m is not None else None,
        "move_5m": round(float(row.move_5m), 2) if row.move_5m is not None else None,
        "move_10m": round(float(row.move_10m), 2) if row.move_10m is not None else None,
        "move_30m": round(float(row.move_30m), 2) if row.move_30m is not None else None,
        "outcome_2m": row.outcome_2m or "Unknown",
        "outcome_3m": row.outcome_3m or "Unknown",
        "outcome_5m": row.outcome_5m or "Unknown",
        "outcome_10m": row.outcome_10m or "Unknown",
        "outcome_30m": row.outcome_30m or "Unknown",
        "reason": row.reason,
    }


def serialize_managed_trade_row(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "engine": row.engine,
        "symbol": row.symbol,
        "entry_signal": row.entry_signal,
        "latest_signal": row.latest_signal,
        "status": row.status,
        "entry_confidence": int(row.entry_confidence or 0),
        "latest_confidence": int(row.latest_confidence or 0),
        "exit_confidence": int(row.exit_confidence) if row.exit_confidence is not None else None,
        "entry_price": round(float(row.entry_price), 2) if row.entry_price is not None else None,
        "latest_price": round(float(row.latest_price), 2) if row.latest_price is not None else None,
        "latest_points": round(float(row.latest_points), 2) if row.latest_points is not None else None,
        "success_threshold_points": round(float(row.success_threshold_points), 2) if row.success_threshold_points is not None else None,
        "stop_points": round(float(row.stop_points), 2) if row.stop_points is not None else None,
        "max_favorable_points": round(float(row.max_favorable_points), 2) if row.max_favorable_points is not None else None,
        "max_adverse_points": round(float(row.max_adverse_points), 2) if row.max_adverse_points is not None else None,
        "hold_cycles": int(row.hold_cycles or 0),
        "exit_signal": row.exit_signal,
        "exit_price": round(float(row.exit_price), 2) if row.exit_price is not None else None,
        "realized_points": round(float(row.realized_points), 2) if row.realized_points is not None else None,
        "result_label": row.result_label,
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "exit_time": row.exit_time.isoformat() if row.exit_time else None,
        "entry_reason": row.entry_reason,
        "exit_reason": row.exit_reason,
    }


async def build_signal_analytics_payload(
    session: AsyncSession,
    *,
    days: int = 7,
    limit: int = 200,
) -> dict[str, Any]:
    from sqlalchemy import desc, select
    from app.models.managed_signal_trade import ManagedSignalTrade
    from app.models.signal_outcome import SignalOutcome

    await refresh_pending_signal_outcomes(session)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await session.execute(
            select(SignalOutcome)
            .where(SignalOutcome.entry_time >= cutoff)
            .order_by(desc(SignalOutcome.entry_time))
            .limit(limit)
        )
    ).scalars().all()

    quick_rows = [row for row in rows if row.engine == "QUICK"]
    main_rows = [row for row in rows if row.engine == "MAIN"]

    managed_rows = (
        await session.execute(
            select(ManagedSignalTrade)
            .where(ManagedSignalTrade.entry_time >= cutoff)
            .order_by(desc(ManagedSignalTrade.entry_time))
            .limit(limit)
        )
    ).scalars().all()
    managed_quick_rows = [row for row in managed_rows if row.engine == "QUICK"]
    managed_main_rows = [row for row in managed_rows if row.engine == "MAIN"]

    quick_signals = [serialize_outcome_row(row) for row in quick_rows]
    long_signals = [serialize_outcome_row(row) for row in main_rows]

    quick_states = [
        CalibrationRow("QUICK", int(row.confidence), preferred_outcome_for_engine("QUICK", row))
        for row in quick_rows
    ]
    long_states = [
        CalibrationRow("MAIN", int(row.confidence), preferred_outcome_for_engine("MAIN", row))
        for row in main_rows
    ]

    quick_won = sum(1 for row in quick_states if row.preferred_outcome == "Won")
    quick_lost = sum(1 for row in quick_states if row.preferred_outcome == "Lost")
    quick_unknown = sum(1 for row in quick_states if row.preferred_outcome == "Unknown")

    long_won = sum(1 for row in long_states if row.preferred_outcome == "Won")
    long_lost = sum(1 for row in long_states if row.preferred_outcome == "Lost")
    long_unknown = sum(1 for row in long_states if row.preferred_outcome == "Unknown")

    quick_decided = quick_won + quick_lost
    long_decided = long_won + long_lost

    def _managed_summary(rows: list[Any]) -> dict[str, Any]:
        won = sum(1 for row in rows if row.result_label == "Won")
        lost = sum(1 for row in rows if row.result_label == "Lost")
        scratch = sum(1 for row in rows if row.result_label == "Scratch")
        open_count = sum(1 for row in rows if row.status == "OPEN")
        decided = won + lost + scratch
        avg_points = (
            round(
                sum(float(row.realized_points or 0) for row in rows if row.realized_points is not None)
                / max(1, sum(1 for row in rows if row.realized_points is not None)),
                1,
            )
            if any(row.realized_points is not None for row in rows)
            else None
        )
        return {
            "total": len(rows),
            "won": won,
            "lost": lost,
            "scratch": scratch,
            "open": open_count,
            "win_rate_pct": round(100 * won / decided, 1) if decided > 0 else None,
            "avg_realized_points": avg_points,
        }

    return {
        "quick_signals": quick_signals,
        "long_signals": long_signals,
        "quick_summary": {
            "total": len(quick_rows),
            "won": quick_won,
            "lost": quick_lost,
            "unknown": quick_unknown,
            "win_rate_pct": round(100 * quick_won / quick_decided, 1) if quick_decided > 0 else None,
        },
        "long_summary": {
            "total": len(main_rows),
            "won": long_won,
            "lost": long_lost,
            "unknown": long_unknown,
            "win_rate_pct": round(100 * long_won / long_decided, 1) if long_decided > 0 else None,
        },
        "managed_quick_trades": [serialize_managed_trade_row(row) for row in managed_quick_rows],
        "managed_long_trades": [serialize_managed_trade_row(row) for row in managed_main_rows],
        "managed_quick_summary": _managed_summary(managed_quick_rows),
        "managed_long_summary": _managed_summary(managed_main_rows),
        "quick_calibration": summarize_calibration(quick_states),
        "long_calibration": summarize_calibration(long_states),
        "days": days,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
