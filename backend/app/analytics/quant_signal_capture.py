"""
Quant outcome capture and segmented calibration helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.analytics.option_contracts import SelectedOptionContract, option_price_at_time, select_option_contract
from app.analytics.quant_signal_context import (
    classify_breakout_class,
    classify_option_outcome,
    classify_regime_label,
    classify_underlying_outcome,
    classify_vol_regime,
    expiry_bucket,
    get_chain_timing_metrics,
    get_nearest_expiry_context,
    get_open_gap_pct,
    get_underlying_price_at_time,
    score_short_covering_risk,
    score_trap,
    session_bucket,
    wall_shift_score,
)
from app.analytics.signal_outcomes import confidence_bucket

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.quant_signal_outcome import QuantSignalOutcome
    from app.models.signal_shadow_decision import SignalShadowDecision

_OUTCOME_HORIZONS = (2, 3, 5, 10, 30)
_OUTCOME_PREFERRED_FIELDS = {
    "QUICK": ("option_outcome_2m", "option_outcome_3m", "option_outcome_5m"),
    "MAIN": ("option_outcome_5m", "option_outcome_10m", "option_outcome_30m"),
}
_DEDUP_WINDOWS = {
    "QUICK": 90,
    "MAIN": 900,
}
_DECISION_DEDUP_SECONDS = 60


@dataclass
class QuantCalibrationRow:
    engine: str
    signal_version: str
    confidence: int
    preferred_outcome: str


@dataclass
class QuantContextFields:
    session_bucket: str | None
    vol_regime: str | None
    breakout_class: str | None
    expiry_bucket: str | None
    regime_label: str | None
    days_to_expiry: int | None
    is_expiry_day: bool
    open_gap_pct: float | None
    data_freshness_seconds: float | None
    snapshot_spacing_std_seconds: float | None
    short_covering_risk_score: int
    trap_score: int
    wall_shift_score: int


def _preferred_outcome(engine: str, row: QuantSignalOutcome) -> str:
    for field in _OUTCOME_PREFERRED_FIELDS.get(engine.upper(), ()):
        value = getattr(row, field, None)
        if value and value != "Unknown":
            return value
    return "Unknown"


def _serialize_quant_row(row: QuantSignalOutcome) -> dict[str, Any]:
    return {
        "id": row.id,
        "engine": row.engine,
        "signal_version": row.signal_version,
        "symbol": row.symbol,
        "signal": row.signal,
        "confidence": int(row.confidence),
        "outlook": row.outlook,
        "state": row.state,
        "entry_ready": bool(row.entry_ready),
        "session_bucket": row.session_bucket,
        "vol_regime": row.vol_regime,
        "breakout_class": row.breakout_class,
        "expiry_bucket": row.expiry_bucket,
        "regime_label": row.regime_label,
        "days_to_expiry": row.days_to_expiry,
        "reason": row.reason,
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "underlying_entry_price": float(row.underlying_entry_price) if row.underlying_entry_price is not None else None,
        "option_entry_ltp": float(row.option_entry_ltp) if row.option_entry_ltp is not None else None,
        "selected_expiry": row.selected_expiry.isoformat() if row.selected_expiry else None,
        "selected_strike": float(row.selected_strike) if row.selected_strike is not None else None,
        "selected_option_type": row.selected_option_type,
        "selected_contract_quality": row.selected_contract_quality,
        "underlying_move_2m": float(row.underlying_move_2m) if row.underlying_move_2m is not None else None,
        "underlying_move_3m": float(row.underlying_move_3m) if row.underlying_move_3m is not None else None,
        "underlying_move_5m": float(row.underlying_move_5m) if row.underlying_move_5m is not None else None,
        "underlying_move_10m": float(row.underlying_move_10m) if row.underlying_move_10m is not None else None,
        "underlying_move_30m": float(row.underlying_move_30m) if row.underlying_move_30m is not None else None,
        "option_move_2m": float(row.option_move_2m) if row.option_move_2m is not None else None,
        "option_move_3m": float(row.option_move_3m) if row.option_move_3m is not None else None,
        "option_move_5m": float(row.option_move_5m) if row.option_move_5m is not None else None,
        "option_move_10m": float(row.option_move_10m) if row.option_move_10m is not None else None,
        "option_move_30m": float(row.option_move_30m) if row.option_move_30m is not None else None,
        "underlying_outcome_2m": row.underlying_outcome_2m or "Unknown",
        "underlying_outcome_3m": row.underlying_outcome_3m or "Unknown",
        "underlying_outcome_5m": row.underlying_outcome_5m or "Unknown",
        "underlying_outcome_10m": row.underlying_outcome_10m or "Unknown",
        "underlying_outcome_30m": row.underlying_outcome_30m or "Unknown",
        "option_outcome_2m": row.option_outcome_2m or "Unknown",
        "option_outcome_3m": row.option_outcome_3m or "Unknown",
        "option_outcome_5m": row.option_outcome_5m or "Unknown",
        "option_outcome_10m": row.option_outcome_10m or "Unknown",
        "option_outcome_30m": row.option_outcome_30m or "Unknown",
    }


def _summarize_calibration(rows: list[QuantCalibrationRow]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        bucket = confidence_bucket(int(row.confidence))
        key = (row.engine, row.signal_version, bucket)
        summary = grouped.setdefault(
            key,
            {
                "engine": row.engine,
                "signal_version": row.signal_version,
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

    ordered = []
    for key in sorted(grouped.keys()):
        summary = grouped[key]
        decided = summary["won"] + summary["lost"]
        summary["win_rate_pct"] = round(100 * summary["won"] / decided, 1) if decided > 0 else None
        ordered.append(summary)
    return ordered


def _segment_summary(rows: list[QuantSignalOutcome], engine: str, field_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = getattr(row, field_name, None) or "Unknown"
        preferred = _preferred_outcome(engine, row)
        summary = grouped.setdefault(
            str(value),
            {"value": str(value), "total": 0, "won": 0, "lost": 0, "unknown": 0, "win_rate_pct": None},
        )
        summary["total"] += 1
        if preferred == "Won":
            summary["won"] += 1
        elif preferred == "Lost":
            summary["lost"] += 1
        else:
            summary["unknown"] += 1

    ordered = []
    for value, summary in sorted(grouped.items(), key=lambda item: (-item[1]["total"], item[0])):
        decided = summary["won"] + summary["lost"]
        summary["win_rate_pct"] = round(100 * summary["won"] / decided, 1) if decided > 0 else None
        ordered.append(summary)
    return ordered


async def build_quant_context(
    session: AsyncSession,
    *,
    symbol: str,
    engine: str,
    signal: str,
    entry_time: datetime,
    current_price: float | None,
    support: float | None,
    resistance: float | None,
    momentum: float | None = None,
    five_min_change_points: float | None = None,
    breakout: bool = False,
    breakdown: bool = False,
    trap_detected: bool = False,
    rangebound: bool = False,
    call_oi_delta: float | None = None,
    put_oi_delta: float | None = None,
    volume_spike: bool = False,
    writer_support: bool = False,
    outlook: str | None = None,
    state: str | None = None,
    entry_ready: bool = False,
    previous_support: float | None = None,
    previous_resistance: float | None = None,
) -> QuantContextFields:
    data_freshness_seconds, snapshot_spacing_std_seconds = await get_chain_timing_metrics(
        session,
        symbol,
        entry_time,
    )
    days_to_expiry, is_expiry_day, expiry_bucket_value = await get_nearest_expiry_context(
        session,
        symbol,
        entry_time,
    )
    open_gap_pct = await get_open_gap_pct(session, symbol, entry_time)
    breakout_class = classify_breakout_class(
        signal=signal,
        breakout=breakout,
        breakdown=breakdown,
        support=support,
        resistance=resistance,
        current_price=current_price,
        momentum=momentum,
        trap_detected=trap_detected,
    )
    short_covering_risk_score = score_short_covering_risk(
        signal=signal,
        call_oi_delta=call_oi_delta,
        put_oi_delta=put_oi_delta,
        breakout=breakout,
        breakdown=breakdown,
        volume_spike=volume_spike,
        writer_support=writer_support,
    )
    trap_score = score_trap(
        trap_detected=trap_detected,
        rangebound=rangebound,
        breakout_class=breakout_class,
    )
    wall_score = wall_shift_score(
        support,
        previous_support,
        resistance,
        previous_resistance,
    )
    vol_regime = classify_vol_regime(
        symbol,
        quick_momentum=momentum,
        five_min_change_points=five_min_change_points,
    )
    regime_label = classify_regime_label(
        engine=engine,
        signal=signal,
        outlook=outlook,
        state=state,
        entry_ready=entry_ready,
        rangebound=rangebound,
        trap_detected=trap_detected,
        expiry_bucket_value=expiry_bucket_value,
        breakout_class=breakout_class,
    )
    return QuantContextFields(
        session_bucket=session_bucket(entry_time),
        vol_regime=vol_regime,
        breakout_class=breakout_class,
        expiry_bucket=expiry_bucket_value,
        regime_label=regime_label,
        days_to_expiry=days_to_expiry,
        is_expiry_day=is_expiry_day,
        open_gap_pct=open_gap_pct,
        data_freshness_seconds=data_freshness_seconds,
        snapshot_spacing_std_seconds=snapshot_spacing_std_seconds,
        short_covering_risk_score=short_covering_risk_score,
        trap_score=trap_score,
        wall_shift_score=wall_score,
    )


async def record_shadow_decision(
    session: AsyncSession,
    *,
    engine: str,
    signal_version: str,
    mode: str,
    symbol: str,
    signal: str,
    confidence: int,
    generated_at: datetime,
    reason: str | None,
    context: QuantContextFields,
    outlook: str | None = None,
    state: str | None = None,
    entry_ready: bool = False,
) -> SignalShadowDecision:
    from sqlalchemy import desc, select
    from app.models.signal_shadow_decision import SignalShadowDecision

    cutoff = generated_at - timedelta(seconds=_DECISION_DEDUP_SECONDS)
    existing = (
        await session.execute(
            select(SignalShadowDecision)
            .where(
                SignalShadowDecision.engine == engine.upper(),
                SignalShadowDecision.signal_version == signal_version,
                SignalShadowDecision.mode == mode.upper(),
                SignalShadowDecision.symbol == symbol,
                SignalShadowDecision.generated_at >= cutoff,
            )
            .order_by(desc(SignalShadowDecision.generated_at))
            .limit(1)
        )
    ).scalars().first()

    if existing is not None:
        existing.signal = signal
        existing.confidence = int(confidence)
        existing.reason = reason
        existing.outlook = outlook
        existing.state = state
        existing.entry_ready = bool(entry_ready)
        existing.session_bucket = context.session_bucket
        existing.vol_regime = context.vol_regime
        existing.breakout_class = context.breakout_class
        existing.expiry_bucket = context.expiry_bucket
        existing.regime_label = context.regime_label
        existing.days_to_expiry = context.days_to_expiry
        existing.data_freshness_seconds = context.data_freshness_seconds
        existing.snapshot_spacing_std_seconds = context.snapshot_spacing_std_seconds
        existing.short_covering_risk_score = context.short_covering_risk_score
        existing.trap_score = context.trap_score
        existing.wall_shift_score = context.wall_shift_score
        existing.generated_at = generated_at
        return existing

    row = SignalShadowDecision(
        engine=engine.upper(),
        signal_version=signal_version,
        mode=mode.upper(),
        symbol=symbol,
        signal=signal,
        confidence=int(confidence),
        outlook=outlook,
        state=state,
        entry_ready=bool(entry_ready),
        session_bucket=context.session_bucket,
        vol_regime=context.vol_regime,
        breakout_class=context.breakout_class,
        expiry_bucket=context.expiry_bucket,
        regime_label=context.regime_label,
        days_to_expiry=context.days_to_expiry,
        data_freshness_seconds=context.data_freshness_seconds,
        snapshot_spacing_std_seconds=context.snapshot_spacing_std_seconds,
        short_covering_risk_score=context.short_covering_risk_score,
        trap_score=context.trap_score,
        wall_shift_score=context.wall_shift_score,
        reason=reason,
        generated_at=generated_at,
    )
    session.add(row)
    await session.flush()
    return row


async def record_quant_signal_candidate(
    session: AsyncSession,
    *,
    engine: str,
    signal_version: str,
    symbol: str,
    signal: str,
    confidence: int,
    entry_time: datetime,
    underlying_entry_price: float,
    reason: str | None,
    context: QuantContextFields,
    outlook: str | None = None,
    state: str | None = None,
    entry_ready: bool = False,
) -> QuantSignalOutcome:
    from sqlalchemy import desc, select
    from app.models.quant_signal_outcome import QuantSignalOutcome

    cutoff = entry_time - timedelta(seconds=_DEDUP_WINDOWS.get(engine.upper(), 300))
    existing = (
        await session.execute(
            select(QuantSignalOutcome)
            .where(
                QuantSignalOutcome.engine == engine.upper(),
                QuantSignalOutcome.signal_version == signal_version,
                QuantSignalOutcome.symbol == symbol,
                QuantSignalOutcome.signal == signal,
                QuantSignalOutcome.entry_time >= cutoff,
            )
            .order_by(desc(QuantSignalOutcome.entry_time))
            .limit(1)
        )
    ).scalars().first()
    if existing is not None:
        return existing

    contract = await select_option_contract(
        session,
        symbol=symbol,
        signal=signal,
        entry_time=entry_time,
        spot_price=underlying_entry_price,
        engine=engine,
    )
    row = QuantSignalOutcome(
        engine=engine.upper(),
        signal_version=signal_version,
        symbol=symbol,
        signal=signal,
        confidence=int(confidence),
        outlook=outlook,
        state=state,
        entry_ready=bool(entry_ready),
        session_bucket=context.session_bucket,
        vol_regime=context.vol_regime,
        breakout_class=context.breakout_class,
        expiry_bucket=context.expiry_bucket,
        regime_label=context.regime_label,
        days_to_expiry=context.days_to_expiry,
        is_expiry_day=context.is_expiry_day,
        open_gap_pct=context.open_gap_pct,
        data_freshness_seconds=context.data_freshness_seconds,
        snapshot_spacing_std_seconds=context.snapshot_spacing_std_seconds,
        short_covering_risk_score=context.short_covering_risk_score,
        trap_score=context.trap_score,
        wall_shift_score=context.wall_shift_score,
        selected_expiry=contract.expiry,
        selected_strike=contract.strike,
        selected_option_type=contract.option_type,
        selected_contract_quality=contract.quality,
        underlying_entry_price=round(float(underlying_entry_price), 2),
        option_entry_ltp=round(float(contract.last_price), 2) if contract.last_price is not None else None,
        reason=reason,
        entry_time=entry_time,
    )
    session.add(row)
    await session.flush()
    return row


def derive_shadow_signal(
    *,
    engine: str,
    signal: str,
    confidence: int,
    context: QuantContextFields,
    entry_ready: bool,
    raw_signal: str | None = None,
) -> tuple[str, int, str]:
    adjusted = int(confidence)
    reasons: list[str] = []
    effective_signal = signal

    if context.data_freshness_seconds is not None and context.data_freshness_seconds > 120:
        adjusted -= 20
        reasons.append("data freshness degraded")
    if context.snapshot_spacing_std_seconds is not None and context.snapshot_spacing_std_seconds > 20:
        adjusted -= 10
        reasons.append("snapshot cadence is uneven")
    if context.short_covering_risk_score >= 65:
        adjusted -= 18
        reasons.append("short-covering risk is elevated")
    if context.trap_score >= 60:
        adjusted -= 35
        reasons.append("trap risk is elevated")
    if context.expiry_bucket == "0DTE" and engine.upper() == "MAIN":
        adjusted -= 10
        reasons.append("same-day expiry adds noise")

    adjusted = max(0, min(100, adjusted))

    if signal in {"Buy CE", "Buy PE"}:
        if context.trap_score >= 60 or context.short_covering_risk_score >= 80:
            effective_signal = "Wait"
        elif engine.upper() == "MAIN" and (not entry_ready or adjusted < 75):
            effective_signal = "Wait"
        elif engine.upper() == "QUICK" and adjusted < 78:
            effective_signal = "Wait"
    elif raw_signal in {"Buy CE", "Buy PE"} and engine.upper() == "QUICK" and adjusted >= 82 and context.trap_score < 40:
        effective_signal = raw_signal
        reasons.append("raw directional impulse is strong enough for shadow promotion")

    reason = "; ".join(reasons) if reasons else "Shadow model stayed aligned with the live decision."
    return effective_signal, adjusted, reason


async def refresh_pending_quant_signal_outcomes(
    session: AsyncSession,
    *,
    lookback_hours: int = 72,
    limit: int = 300,
) -> int:
    from sqlalchemy import select
    from app.models.quant_signal_outcome import QuantSignalOutcome

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=lookback_hours)
    rows = (
        await session.execute(
            select(QuantSignalOutcome)
            .where(QuantSignalOutcome.entry_time >= cutoff)
            .order_by(QuantSignalOutcome.entry_time.asc())
            .limit(limit)
        )
    ).scalars().all()

    updated = 0
    for row in rows:
        row_updated = False
        contract = SelectedOptionContract(
            expiry=row.selected_expiry,
            strike=float(row.selected_strike) if row.selected_strike is not None else None,
            option_type=row.selected_option_type,
            last_price=float(row.option_entry_ltp) if row.option_entry_ltp is not None else None,
            quality=row.selected_contract_quality,
            snapshot_time=row.entry_time,
        )
        for horizon in _OUTCOME_HORIZONS:
            underlying_field = f"underlying_price_{horizon}m"
            underlying_move_field = f"underlying_move_{horizon}m"
            underlying_outcome_field = f"underlying_outcome_{horizon}m"
            option_field = f"option_price_{horizon}m"
            option_move_field = f"option_move_{horizon}m"
            option_outcome_field = f"option_outcome_{horizon}m"
            if getattr(row, underlying_field) is not None or getattr(row, option_field) is not None:
                continue

            target = row.entry_time
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            target = target + timedelta(minutes=horizon)
            if now_utc < target:
                continue

            tolerance = 4 if horizon <= 3 else 8 if horizon <= 10 else 18
            later_underlying = await get_underlying_price_at_time(
                session,
                row.symbol,
                target,
                tolerance_minutes=tolerance,
            )
            later_option = await option_price_at_time(
                session,
                symbol=row.symbol,
                contract=contract,
                target=target,
                tolerance_minutes=tolerance,
            )

            if later_underlying is not None:
                move = round(later_underlying - float(row.underlying_entry_price), 2)
                setattr(row, underlying_field, round(later_underlying, 2))
                setattr(row, underlying_move_field, move)
                setattr(
                    row,
                    underlying_outcome_field,
                    classify_underlying_outcome(row.signal, float(row.underlying_entry_price), later_underlying),
                )
                row_updated = True
            elif now_utc >= target + timedelta(minutes=tolerance):
                setattr(row, underlying_outcome_field, "Unknown")
                row_updated = True

            if later_option is not None and row.option_entry_ltp is not None:
                move = round(later_option - float(row.option_entry_ltp), 2)
                setattr(row, option_field, round(later_option, 2))
                setattr(row, option_move_field, move)
                setattr(
                    row,
                    option_outcome_field,
                    classify_option_outcome(float(row.option_entry_ltp), later_option),
                )
                row_updated = True
            elif now_utc >= target + timedelta(minutes=tolerance):
                setattr(row, option_outcome_field, "Unknown")
                row_updated = True

        if row_updated:
            row.updated_at = now_utc
            updated += 1
    return updated


async def build_quant_signal_analytics_payload(
    session: AsyncSession,
    *,
    days: int = 14,
    limit: int = 300,
) -> dict[str, Any]:
    from sqlalchemy import desc, select
    from app.models.quant_signal_outcome import QuantSignalOutcome
    from app.models.signal_shadow_decision import SignalShadowDecision

    await refresh_pending_quant_signal_outcomes(session)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await session.execute(
            select(QuantSignalOutcome)
            .where(QuantSignalOutcome.entry_time >= cutoff)
            .order_by(desc(QuantSignalOutcome.entry_time))
            .limit(limit)
        )
    ).scalars().all()
    quick_rows = [row for row in rows if row.engine == "QUICK"]
    main_rows = [row for row in rows if row.engine == "MAIN"]

    def _summary(engine_rows: list[QuantSignalOutcome], engine_name: str) -> dict[str, Any]:
        preferred = [_preferred_outcome(engine_name, row) for row in engine_rows]
        won = sum(1 for value in preferred if value == "Won")
        lost = sum(1 for value in preferred if value == "Lost")
        unknown = sum(1 for value in preferred if value == "Unknown")
        decided = won + lost
        return {
            "total": len(engine_rows),
            "won": won,
            "lost": lost,
            "unknown": unknown,
            "win_rate_pct": round(100 * won / decided, 1) if decided > 0 else None,
        }

    calibration_rows = [
        QuantCalibrationRow(
            row.engine,
            row.signal_version,
            int(row.confidence),
            _preferred_outcome(row.engine, row),
        )
        for row in rows
    ]

    decisions = (
        await session.execute(
            select(SignalShadowDecision)
            .where(SignalShadowDecision.generated_at >= cutoff)
            .order_by(desc(SignalShadowDecision.generated_at))
            .limit(limit * 4)
        )
    ).scalars().all()

    def _decision_counts(engine: str) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in decisions:
            if row.engine != engine:
                continue
            key = (row.signal_version, row.signal)
            bucket = grouped.setdefault(
                key,
                {"signal_version": row.signal_version, "signal": row.signal, "total": 0, "avg_confidence": 0.0},
            )
            bucket["total"] += 1
            bucket["avg_confidence"] += int(row.confidence or 0)
        output = []
        for summary in grouped.values():
            if summary["total"] > 0:
                summary["avg_confidence"] = round(summary["avg_confidence"] / summary["total"], 1)
            output.append(summary)
        return sorted(output, key=lambda item: (-item["total"], item["signal_version"], item["signal"]))

    return {
        "quick_quant_signals": [_serialize_quant_row(row) for row in quick_rows],
        "long_quant_signals": [_serialize_quant_row(row) for row in main_rows],
        "quick_quant_summary": _summary(quick_rows, "QUICK"),
        "long_quant_summary": _summary(main_rows, "MAIN"),
        "quant_calibration": _summarize_calibration(calibration_rows),
        "quick_segments": {
            "session_bucket": _segment_summary(quick_rows, "QUICK", "session_bucket"),
            "vol_regime": _segment_summary(quick_rows, "QUICK", "vol_regime"),
            "breakout_class": _segment_summary(quick_rows, "QUICK", "breakout_class"),
            "expiry_bucket": _segment_summary(quick_rows, "QUICK", "expiry_bucket"),
            "regime_label": _segment_summary(quick_rows, "QUICK", "regime_label"),
        },
        "long_segments": {
            "session_bucket": _segment_summary(main_rows, "MAIN", "session_bucket"),
            "vol_regime": _segment_summary(main_rows, "MAIN", "vol_regime"),
            "breakout_class": _segment_summary(main_rows, "MAIN", "breakout_class"),
            "expiry_bucket": _segment_summary(main_rows, "MAIN", "expiry_bucket"),
            "regime_label": _segment_summary(main_rows, "MAIN", "regime_label"),
        },
        "quick_decision_mix": _decision_counts("QUICK"),
        "long_decision_mix": _decision_counts("MAIN"),
    }
