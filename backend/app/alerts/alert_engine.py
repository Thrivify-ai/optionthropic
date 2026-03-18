"""
Alert engine — evaluates rule-based conditions against latest analytics,
persists alerts to the database, and publishes them to Amazon SQS.

Alert types:
  LARGE_FLOW        — single strike premium spike
  OI_SPIKE          — open interest jump > threshold %
  GAMMA_WALL        — price within N points of a wall
  POSITIONING_SHIFT — dominant shift signal detected
  MAX_PAIN_DRIFT    — spot deviating > 2 % from max pain
  TIME_FACTOR       — key intraday window (10:30–10:55, 12:30, 1:20, 2:55 PM IST) + directional bias
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
from sqlalchemy import select
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.positioning_shift import detect_positioning_shifts
from app.analytics.time_factor import get_current_window, get_time_factor_bias
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.alert import Alert

logger = get_logger(__name__)

# ─── Thresholds ────────────────────────────────────────────────────────────────
LARGE_FLOW_PREMIUM = 10_000_000    # ₹1 crore
GAMMA_WALL_PROXIMITY_POINTS = 50   # within 50 pts of wall
MAX_PAIN_DRIFT_PCT = 2.0           # 2 % deviation
OI_SPIKE_PCT = 15.0                # 15 % OI change


# ─── SQS helper ────────────────────────────────────────────────────────────────

def _get_sqs():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


async def _publish_alert_to_sqs(alert_payload: dict[str, Any]) -> None:
    if not settings.sqs_queue_url:
        return
    try:
        loop = asyncio.get_event_loop()
        client = _get_sqs()
        await loop.run_in_executor(
            None,
            lambda: client.send_message(
                QueueUrl=settings.sqs_queue_url,
                MessageBody=json.dumps(alert_payload),
                MessageAttributes={
                    "AlertType": {
                        "StringValue": alert_payload.get("alert_type", "UNKNOWN"),
                        "DataType": "String",
                    }
                },
            ),
        )
        logger.debug("Alert published to SQS", alert_type=alert_payload.get("alert_type"))
    except (BotoCoreError, ClientError) as exc:
        logger.warning("SQS alert publish failed", error=str(exc))


# ─── Persist and publish helper ────────────────────────────────────────────────

async def _save_alert(
    session: AsyncSession,
    symbol: str,
    alert_type: str,
    description: str,
    severity: str = "INFO",
) -> Alert:
    now = datetime.now(timezone.utc)
    alert = Alert(
        symbol=symbol,
        alert_type=alert_type,
        description=description,
        severity=severity,
        timestamp=now,
    )
    session.add(alert)
    await session.flush()

    payload = {
        "alert_id": alert.id,
        "symbol": symbol,
        "alert_type": alert_type,
        "description": description,
        "severity": severity,
        "timestamp": now.isoformat(),
    }
    await _publish_alert_to_sqs(payload)
    return alert


# ─── Individual alert rules ────────────────────────────────────────────────────

async def _check_large_flow(session: AsyncSession, symbol: str) -> list[Alert]:
    alerts = []
    flow_data = await detect_options_flow(session, symbol)
    for flow in flow_data.get("flows", []):
        if flow["premium"] >= LARGE_FLOW_PREMIUM:
            desc = (
                f"Large {flow['flow_type']} detected at {symbol} "
                f"strike {flow['strike']} — premium ₹{flow['premium']:,.0f} "
                f"({flow['option_type']} {flow['side']})"
            )
            alert = await _save_alert(session, symbol, "LARGE_FLOW", desc, severity="HIGH")
            alerts.append(alert)
    return alerts


async def _check_gamma_wall(session: AsyncSession, symbol: str) -> list[Alert]:
    alerts = []
    gw = await compute_gamma_walls(session, symbol)
    spot = gw.get("underlying_price")
    if not spot:
        return []

    for wall_key, label in (("call_wall", "CALL"), ("put_wall", "PUT")):
        wall = gw.get(wall_key)
        if wall and abs(spot - wall) <= GAMMA_WALL_PROXIMITY_POINTS:
            desc = (
                f"{symbol} spot ({spot}) is within {GAMMA_WALL_PROXIMITY_POINTS} points "
                f"of {label} gamma wall at {wall}"
            )
            alert = await _save_alert(session, symbol, "GAMMA_WALL", desc, severity="MEDIUM")
            alerts.append(alert)
    return alerts


async def _check_max_pain_drift(session: AsyncSession, symbol: str) -> list[Alert]:
    alerts = []
    mp_data = await compute_max_pain(session, symbol)
    spot = mp_data.get("underlying_price")
    mp = mp_data.get("max_pain_strike")
    if not spot or not mp:
        return []

    drift_pct = abs((spot - mp) / mp * 100)
    if drift_pct >= MAX_PAIN_DRIFT_PCT:
        direction = "above" if spot > mp else "below"
        desc = (
            f"{symbol} spot ({spot}) is {drift_pct:.1f}% {direction} max pain ({mp}). "
            f"Expiry reversion pressure likely."
        )
        alert = await _save_alert(session, symbol, "MAX_PAIN_DRIFT", desc, severity="MEDIUM")
        alerts.append(alert)
    return alerts


async def _check_positioning_shift(session: AsyncSession, symbol: str) -> list[Alert]:
    alerts = []
    ps_data = await detect_positioning_shifts(session, symbol)
    if not ps_data.get("shifts"):
        return []

    dominant_signals: dict[str, int] = {}
    for shift in ps_data["shifts"]:
        for sig in (shift["call_signal"], shift["put_signal"]):
            dominant_signals[sig] = dominant_signals.get(sig, 0) + 1

    if dominant_signals:
        top_signal = max(dominant_signals, key=dominant_signals.get)  # type: ignore[arg-type]
        count = dominant_signals[top_signal]
        if count >= 3:
            desc = (
                f"{symbol} showing dominant {top_signal} pattern "
                f"across {count} strikes (spot {ps_data.get('underlying_price')})"
            )
            alert = await _save_alert(
                session, symbol, "POSITIONING_SHIFT", desc, severity="MEDIUM"
            )
            alerts.append(alert)
    return alerts


async def _check_time_factor(session: AsyncSession, symbol: str) -> list[Alert]:
    """Fire TIME_FACTOR alert when in a key intraday window and options show clear bias.
    Dedupe: at most one TIME_FACTOR per symbol per 15 minutes."""
    alerts = []
    window = get_current_window()
    if not window:
        return []

    bias = await get_time_factor_bias(session, symbol)
    if bias not in ("BULLISH", "BEARISH"):
        return []

    # Avoid spamming: skip if we already fired TIME_FACTOR for this symbol recently
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    stmt = (
        select(Alert)
        .where(
            Alert.symbol == symbol,
            Alert.alert_type == "TIME_FACTOR",
            Alert.timestamp >= cutoff,
        )
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing:
        return []

    desc = (
        f"Time factor: {window['label']} — {bias.capitalize()} bias from options buildup. "
        f"{window.get('description', '')}"
    )
    alert = await _save_alert(
        session, symbol, "TIME_FACTOR", desc, severity="MEDIUM"
    )
    alerts.append(alert)
    return alerts


# ─── Main evaluation entry point ──────────────────────────────────────────────

async def run_alert_evaluation(symbol: str) -> list[dict]:
    """Run all alert rules for a symbol. Returns list of alert dicts."""
    fired: list[dict] = []

    async with AsyncSessionLocal() as session:
        for checker in (
            _check_large_flow,
            _check_gamma_wall,
            _check_max_pain_drift,
            _check_positioning_shift,
            _check_time_factor,
        ):
            try:
                new_alerts = await checker(session, symbol)
                for a in new_alerts:
                    fired.append(
                        {
                            "id": a.id,
                            "symbol": a.symbol,
                            "alert_type": a.alert_type,
                            "description": a.description,
                            "severity": a.severity,
                            "timestamp": a.timestamp.isoformat(),
                        }
                    )
            except Exception as exc:
                logger.error(
                    "Alert rule failed",
                    symbol=symbol,
                    rule=checker.__name__,
                    error=str(exc),
                )

        await session.commit()

    logger.info("Alert evaluation complete", symbol=symbol, fired=len(fired))
    return fired


async def run_all_symbols() -> None:
    """Run alert evaluation for all supported symbols."""
    tasks = [run_alert_evaluation(sym) for sym in settings.supported_symbols]
    await asyncio.gather(*tasks, return_exceptions=True)
