from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.quant_signal_capture import (
    build_quant_context,
    derive_shadow_signal,
    record_quant_signal_candidate,
    record_shadow_decision,
)
from app.analytics.signal_outcomes import record_signal_outcome_candidate


async def capture_quick_quant_observation(
    session: AsyncSession,
    *,
    symbol: str,
    payload: dict[str, Any],
) -> None:
    now_utc = datetime.now(timezone.utc)
    current_price = payload.get("current_price")
    live_signal = payload.get("quick_signal") or "Wait"
    raw_signal = payload.get("raw_signal") or live_signal
    context_signal = raw_signal if raw_signal in ("Buy CE", "Buy PE") else live_signal
    confidence = int(payload.get("confidence", 0) or 0)
    state = str(payload.get("state") or "idle")
    entry_ready = live_signal in ("Buy CE", "Buy PE")

    context = await build_quant_context(
        session,
        symbol=symbol,
        engine="QUICK",
        signal=context_signal,
        entry_time=now_utc,
        current_price=float(current_price) if current_price is not None else None,
        support=float(payload["support"]) if payload.get("support") is not None else None,
        resistance=float(payload["resistance"]) if payload.get("resistance") is not None else None,
        momentum=float(payload["momentum"]) if payload.get("momentum") is not None else None,
        breakout=bool(payload.get("breakout")),
        breakdown=bool(payload.get("breakdown")),
        trap_detected=bool(payload.get("trap_detected")),
        rangebound=bool(payload.get("rangebound")),
        call_oi_delta=float(payload["call_oi_delta"]) if payload.get("call_oi_delta") is not None else None,
        put_oi_delta=float(payload["put_oi_delta"]) if payload.get("put_oi_delta") is not None else None,
        volume_spike=bool(payload.get("volume_spike")),
        writer_support=bool(payload.get("oi_confirmed")),
        state=state,
        entry_ready=entry_ready,
    )

    await record_shadow_decision(
        session,
        engine="QUICK",
        signal_version="quick_v4_live",
        mode="LIVE",
        symbol=symbol,
        signal=live_signal,
        confidence=confidence,
        generated_at=now_utc,
        reason=payload.get("reason"),
        context=context,
        state=state,
        entry_ready=entry_ready,
    )

    shadow_signal, shadow_confidence, shadow_reason = derive_shadow_signal(
        engine="QUICK",
        signal=live_signal,
        confidence=confidence,
        context=context,
        entry_ready=entry_ready,
        raw_signal=raw_signal,
    )
    await record_shadow_decision(
        session,
        engine="QUICK",
        signal_version="quick_v4_shadow",
        mode="SHADOW",
        symbol=symbol,
        signal=shadow_signal,
        confidence=shadow_confidence,
        generated_at=now_utc,
        reason=shadow_reason,
        context=context,
        state=state,
        entry_ready=shadow_signal in ("Buy CE", "Buy PE"),
    )

    if (
        current_price is not None
        and live_signal in ("Buy CE", "Buy PE")
        and payload.get("trade_action") == "entry"
    ):
        await record_signal_outcome_candidate(
            session,
            engine="QUICK",
            symbol=symbol,
            signal=live_signal,
            confidence=confidence,
            entry_price=float(current_price),
            entry_time=now_utc,
            reason=payload.get("reason"),
            state=state,
        )

    if current_price is not None and live_signal in ("Buy CE", "Buy PE"):
        await record_quant_signal_candidate(
            session,
            engine="QUICK",
            signal_version="quick_v4_live",
            symbol=symbol,
            signal=live_signal,
            confidence=confidence,
            entry_time=now_utc,
            underlying_entry_price=float(current_price),
            reason=payload.get("reason"),
            context=context,
            state=state,
            entry_ready=True,
        )

    if current_price is not None and shadow_signal in ("Buy CE", "Buy PE"):
        await record_quant_signal_candidate(
            session,
            engine="QUICK",
            signal_version="quick_v4_shadow",
            symbol=symbol,
            signal=shadow_signal,
            confidence=shadow_confidence,
            entry_time=now_utc,
            underlying_entry_price=float(current_price),
            reason=shadow_reason,
            context=context,
            state=state,
            entry_ready=True,
        )
