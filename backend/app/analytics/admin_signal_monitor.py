"""
Admin signal monitor payload helpers.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.managed_signal_trade import ManagedSignalTrade
from app.models.signal_shadow_decision import SignalShadowDecision

_SUPPORTED_ENGINES = ("QUICK", "MAIN", "COMMODITY_QUICK", "COMMODITY_LONG")
_ENTRY_BLOCK_PREFIX = "entry blocked:"
_IST_ZONE = "Asia/Calcutta"


def _read_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key, default)
    return getattr(row, key, default)


def _empty_engine_decision_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "trade_event_total": 0,
        "entry_total": 0,
        "no_trade_total": 0,
        "buy_ce": 0,
        "buy_pe": 0,
        "long": 0,
        "short": 0,
        "hold": 0,
        "exit": 0,
        "wait": 0,
        "other": 0,
        "buy_total": 0,
        "buy_share_pct": None,
        "entry_share_pct": None,
        "wait_share_pct": None,
        "avg_confidence": None,
        "_weighted_confidence": 0.0,
        "_weighted_total": 0,
    }


def _signal_bucket(signal: str | None) -> str:
    normalized = (signal or "").strip().lower()
    if normalized == "buy ce":
        return "buy_ce"
    if normalized == "buy pe":
        return "buy_pe"
    if normalized == "long":
        return "long"
    if normalized == "short":
        return "short"
    if normalized.startswith("hold"):
        return "hold"
    if normalized.startswith("exit"):
        return "exit"
    if normalized == "wait":
        return "wait"
    return "other"


def summarize_decision_rows(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """
    Build per-engine LIVE signal mix summary from aggregated DB rows.
    """
    summary: dict[str, dict[str, Any]] = {
        engine: _empty_engine_decision_bucket() for engine in _SUPPORTED_ENGINES
    }

    for row in rows:
        engine = str(_read_value(row, "engine", "")).upper().strip()
        if not engine:
            continue
        bucket = summary.setdefault(engine, _empty_engine_decision_bucket())
        count = int(_read_value(row, "total", 0) or 0)
        signal_key = _signal_bucket(_read_value(row, "signal"))
        avg_confidence = _read_value(row, "avg_confidence")

        bucket[signal_key] += count
        bucket["total"] += count
        if avg_confidence is not None and count > 0:
            bucket["_weighted_confidence"] += float(avg_confidence) * count
            bucket["_weighted_total"] += count

    for bucket in summary.values():
        total = int(bucket["total"])
        buy_total = int(bucket["buy_ce"]) + int(bucket["buy_pe"]) + int(bucket["long"]) + int(bucket["short"])
        trade_event_total = buy_total + int(bucket["hold"]) + int(bucket["exit"])
        wait_total = int(bucket["wait"])
        no_trade_total = wait_total + int(bucket["other"])
        bucket["buy_total"] = buy_total
        bucket["entry_total"] = buy_total
        bucket["trade_event_total"] = trade_event_total
        bucket["no_trade_total"] = no_trade_total
        bucket["buy_share_pct"] = round(100 * buy_total / total, 1) if total > 0 else None
        bucket["entry_share_pct"] = (
            round(100 * buy_total / trade_event_total, 1)
            if trade_event_total > 0
            else None
        )
        bucket["wait_share_pct"] = round(100 * wait_total / total, 1) if total > 0 else None
        if int(bucket["_weighted_total"]) > 0:
            bucket["avg_confidence"] = round(
                float(bucket["_weighted_confidence"]) / int(bucket["_weighted_total"]),
                1,
            )
        bucket.pop("_weighted_confidence", None)
        bucket.pop("_weighted_total", None)

    return summary


def clean_entry_block_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = " ".join(str(reason).split())
    if not normalized:
        return None
    if normalized.lower().startswith(_ENTRY_BLOCK_PREFIX):
        normalized = normalized[len(_ENTRY_BLOCK_PREFIX) :].strip()
    return normalized or None


def summarize_entry_block_rows(
    rows: Iterable[Any],
    *,
    top_n: int = 8,
) -> dict[str, dict[str, Any]]:
    """
    Build top entry-block reasons by engine.
    """
    grouped: dict[str, dict[str, int]] = {
        engine: defaultdict(int) for engine in _SUPPORTED_ENGINES
    }

    for row in rows:
        engine = str(_read_value(row, "engine", "")).upper().strip()
        if not engine:
            continue
        reason = clean_entry_block_reason(_read_value(row, "reason"))
        if reason is None:
            continue
        count = int(_read_value(row, "total", 0) or 0)
        grouped.setdefault(engine, defaultdict(int))[reason] += count

    output: dict[str, dict[str, Any]] = {}
    for engine, reasons in grouped.items():
        total = sum(int(v) for v in reasons.values())
        ordered = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        top = [
            {
                "reason": reason,
                "count": count,
                "share_pct": round(100 * count / total, 1) if total > 0 else None,
            }
            for reason, count in ordered[:top_n]
        ]
        output[engine] = {
            "total": total,
            "top_reasons": top,
        }
    return output


def serialize_managed_daily_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for row in rows:
        won = int(_read_value(row, "won", 0) or 0)
        lost = int(_read_value(row, "lost", 0) or 0)
        scratch = int(_read_value(row, "scratch", 0) or 0)
        decided = won + lost + scratch
        net_points = _read_value(row, "net_points")
        avg_points = _read_value(row, "avg_points")
        serialized.append(
            {
                "trade_day": str(_read_value(row, "trade_day")),
                "engine": str(_read_value(row, "engine", "")).upper(),
                "total": int(_read_value(row, "total", 0) or 0),
                "won": won,
                "lost": lost,
                "scratch": scratch,
                "win_rate_pct": round(100 * won / decided, 1) if decided > 0 else None,
                "net_points": round(float(net_points), 2) if net_points is not None else 0.0,
                "avg_points": round(float(avg_points), 2) if avg_points is not None else None,
            }
        )
    return serialized


async def _query_decision_window_rows(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> list[Any]:
    rows = (
        await session.execute(
            select(
                SignalShadowDecision.engine.label("engine"),
                SignalShadowDecision.signal.label("signal"),
                func.count().label("total"),
                func.avg(SignalShadowDecision.confidence).label("avg_confidence"),
            )
            .where(
                SignalShadowDecision.mode == "LIVE",
                SignalShadowDecision.engine.in_(_SUPPORTED_ENGINES),
                SignalShadowDecision.generated_at >= cutoff,
            )
            .group_by(SignalShadowDecision.engine, SignalShadowDecision.signal)
        )
    ).all()
    return list(rows)


async def _query_entry_block_rows(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> list[Any]:
    rows = (
        await session.execute(
            select(
                SignalShadowDecision.engine.label("engine"),
                SignalShadowDecision.reason.label("reason"),
                func.count().label("total"),
            )
            .where(
                SignalShadowDecision.mode == "LIVE",
                SignalShadowDecision.engine.in_(_SUPPORTED_ENGINES),
                SignalShadowDecision.generated_at >= cutoff,
                SignalShadowDecision.reason.is_not(None),
                SignalShadowDecision.reason.ilike("Entry blocked:%"),
            )
            .group_by(SignalShadowDecision.engine, SignalShadowDecision.reason)
            .order_by(desc(func.count()))
        )
    ).all()
    return list(rows)


async def _query_managed_daily_rows(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> list[Any]:
    trade_day = func.to_char(
        func.timezone(_IST_ZONE, ManagedSignalTrade.entry_time),
        "YYYY-MM-DD",
    ).label("trade_day")
    rows = (
        await session.execute(
            select(
                trade_day,
                ManagedSignalTrade.engine.label("engine"),
                func.count().label("total"),
                func.sum(case((ManagedSignalTrade.result_label == "Won", 1), else_=0)).label("won"),
                func.sum(case((ManagedSignalTrade.result_label == "Lost", 1), else_=0)).label("lost"),
                func.sum(case((ManagedSignalTrade.result_label == "Scratch", 1), else_=0)).label("scratch"),
                func.sum(func.coalesce(ManagedSignalTrade.realized_points, 0)).label("net_points"),
                func.avg(ManagedSignalTrade.realized_points).label("avg_points"),
            )
            .where(
                ManagedSignalTrade.engine.in_(_SUPPORTED_ENGINES),
                ManagedSignalTrade.entry_time >= cutoff,
            )
            .group_by(trade_day, ManagedSignalTrade.engine)
            .order_by(desc(trade_day), ManagedSignalTrade.engine)
        )
    ).all()
    return list(rows)


async def build_admin_signal_monitor_payload(
    session: AsyncSession,
    *,
    days: int = 14,
    decision_windows_hours: tuple[int, ...] = (3, 24),
    reason_limit: int = 8,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    decision_windows: dict[str, dict[str, Any]] = {}

    for hours in decision_windows_hours:
        cutoff = now_utc - timedelta(hours=max(1, int(hours)))
        rows = await _query_decision_window_rows(session, cutoff=cutoff)
        decision_windows[f"{int(hours)}h"] = summarize_decision_rows(rows)

    blocks_cutoff = now_utc - timedelta(hours=24)
    block_rows = await _query_entry_block_rows(session, cutoff=blocks_cutoff)
    entry_blocks = summarize_entry_block_rows(block_rows, top_n=max(1, int(reason_limit)))

    managed_cutoff = now_utc - timedelta(days=max(1, int(days)))
    managed_rows = await _query_managed_daily_rows(session, cutoff=managed_cutoff)
    managed_daily_pnl = serialize_managed_daily_rows(managed_rows)

    return {
        "signal_monitor": {
            "decision_windows": decision_windows,
            "entry_block_reasons_24h": entry_blocks,
            "managed_daily_pnl": managed_daily_pnl,
            "days": max(1, int(days)),
            "timestamp": now_utc.isoformat(),
        }
    }
