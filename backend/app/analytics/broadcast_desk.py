"""
Manual broadcast-desk content generation and persistence.

This powers a copy-first publishing workflow inside the app so the team can
generate, review, approve, and manually publish WhatsApp/Telegram-ready drafts.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone
import enum
from typing import Any

from app.services.market_hours import to_ist

try:
    from sqlalchemy import desc, select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.broadcast_draft import BroadcastDraft, BroadcastDraftStatus
except Exception:  # pragma: no cover - test fallback when SQLAlchemy is unavailable
    AsyncSession = object  # type: ignore[assignment]
    desc = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

    class BroadcastDraftStatus(str, enum.Enum):
        DRAFT = "draft"
        APPROVED = "approved"
        PUBLISHED = "published"

    BroadcastDraft = Any  # type: ignore[assignment]

_SYMBOL_WEIGHTS = {
    "NIFTY": 1.5,
    "BANKNIFTY": 1.1,
    "SENSEX": 0.9,
}

_LINK_VARIANTS = (
    ("https://optionthropic.com?src=wa_bias_a", "More context on optionthropic.com"),
    ("https://optionthropic.com?src=wa_bias_b", "Live desk notes: optionthropic.com"),
    ("https://optionthropic.com?src=wa_bias_c", "Detailed context lives on optionthropic.com"),
    ("https://optionthropic.com?src=wa_bias_d", "Follow the live desk on optionthropic.com"),
    ("https://optionthropic.com?src=wa_bias_e", "Extra context is on optionthropic.com"),
)

_POST_ORDER = {
    "MORNING_BIAS": 0,
    "INTRADAY_UPDATE": 1,
    "CLOSING_WRAP": 2,
    "NEWS_ALERT": 3,
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_channel_type(channel_type: str | None) -> str:
    value = (channel_type or "WHATSAPP").strip().upper()
    return value or "WHATSAPP"


def _rotate_link(post_key: str, generated_at: datetime) -> dict[str, str]:
    freshness_bucket = generated_at.hour * 4 + (generated_at.minute // 15)
    index = (
        generated_at.toordinal()
        + freshness_bucket
        + sum(ord(ch) for ch in post_key)
    ) % len(_LINK_VARIANTS)
    url, label = _LINK_VARIANTS[index]
    return {"url": url, "label": label}


def _headline_truncate(text: str, *, limit: int = 88) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _market_bias_snapshot(symbols: dict[str, Any]) -> dict[str, Any]:
    weighted_score = 0.0
    total_weight = 0.0
    symbol_notes: list[str] = []

    for symbol, payload in symbols.items():
        trading = payload.get("trading_signal") or {}
        outlook = str(trading.get("outlook") or "Neutral")
        state = str(trading.get("state") or "idle")
        confidence = _safe_int(trading.get("confidence"), 0)
        weight = _SYMBOL_WEIGHTS.get(symbol, 1.0)

        directional_score = 0.0
        if outlook == "Bullish":
            directional_score = weight * max(confidence, 45) / 100.0
        elif outlook == "Bearish":
            directional_score = -weight * max(confidence, 45) / 100.0

        weighted_score += directional_score
        total_weight += weight
        symbol_notes.append(f"{symbol}: {outlook} ({confidence}%) · {state}")

    normalized = weighted_score / total_weight if total_weight else 0.0
    if normalized >= 0.22:
        bias = "Bullish"
    elif normalized <= -0.22:
        bias = "Bearish"
    else:
        bias = "Neutral"

    probability = int(round(52 + min(abs(normalized), 0.95) * 34))
    if bias == "Neutral":
        probability = max(50, probability - 6)

    return {
        "bias": bias,
        "probability": max(50, min(86, probability)),
        "score": round(normalized, 3),
        "symbol_notes": symbol_notes,
    }


def _news_summary(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    if not alerts:
        return {
            "impact_score": 0,
            "headlines": [],
            "headline_lines": ["No critical global alert is dominating the desk right now."],
            "expectation": "Bias should follow local structure more than headline risk for now.",
        }

    top_alerts = alerts[:2]
    impact_score = max(_safe_int(alert.get("impact_score"), 0) for alert in top_alerts)
    headline_lines = [
        f"- {_headline_truncate(alert.get('title') or 'Untitled')} ({alert.get('impact_score', 0)}/100)"
        for alert in top_alerts
    ]
    expectation = (
        "News risk is elevated, so conviction should come from both structure and follow-through."
        if impact_score >= 80
        else "News is relevant, but price structure still needs to confirm the move."
    )
    return {
        "impact_score": impact_score,
        "headlines": top_alerts,
        "headline_lines": headline_lines,
        "expectation": expectation,
    }


def _market_watch_lines(symbols: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for symbol in ("NIFTY", "BANKNIFTY", "SENSEX"):
        payload = symbols.get(symbol) or {}
        trading = payload.get("trading_signal") or {}
        support = trading.get("support")
        resistance = trading.get("resistance")
        outlook = trading.get("outlook") or "Neutral"
        parts = [f"{symbol}: {outlook}"]
        if support is not None:
            parts.append(f"S {int(round(float(support)))}")
        if resistance is not None:
            parts.append(f"R {int(round(float(resistance)))}")
        lines.append(" · ".join(parts))
    return lines


def _post_text(
    *,
    title: str,
    bias: str,
    probability: int,
    news_impact_score: int,
    bullets: list[str],
    closing_lines: list[str],
    link: dict[str, str],
) -> str:
    header = [
        title,
        f"Bias: {bias} {probability}%",
        f"News impact: {news_impact_score}/100",
        "",
    ]
    body = bullets + [""] + closing_lines + ["", f"{link['label']}: {link['url']}"]
    return "\n".join(header + body).strip()


def _build_posts(
    *,
    generated_at: datetime,
    bias_snapshot: dict[str, Any],
    news_summary: dict[str, Any],
    symbols: dict[str, Any],
) -> dict[str, Any]:
    bias = str(bias_snapshot["bias"])
    probability = int(bias_snapshot["probability"])
    impact_score = int(news_summary["impact_score"])
    watch_lines = _market_watch_lines(symbols)

    morning_link = _rotate_link("morning", generated_at)
    intraday_link = _rotate_link("intraday", generated_at)
    closing_link = _rotate_link("closing", generated_at)

    morning = _post_text(
        title="Optionthropic Morning Bias",
        bias=bias,
        probability=probability,
        news_impact_score=impact_score,
        bullets=[
            "What is shaping the day:",
            *news_summary["headline_lines"],
            *[f"- {line}" for line in watch_lines],
        ],
        closing_lines=[
            "What to watch early:",
            f"- {news_summary['expectation']}",
            "- If opening follow-through fails, the bias can weaken quickly.",
        ],
        link=morning_link,
    )

    intraday = _post_text(
        title="Optionthropic Intraday Pulse",
        bias=bias,
        probability=probability,
        news_impact_score=impact_score,
        bullets=[
            "Current desk read:",
            *[f"- {note}" for note in bias_snapshot["symbol_notes"]],
            f"- {news_summary['expectation']}",
        ],
        closing_lines=[
            "What changes this read:",
            "- A sharp shift in BankNifty leadership",
            "- Fresh global headline risk or a failed move at key levels",
        ],
        link=intraday_link,
    )

    closing = _post_text(
        title="Optionthropic Closing Wrap",
        bias=bias,
        probability=probability,
        news_impact_score=impact_score,
        bullets=[
            "What happened today:",
            *[f"- {note}" for note in bias_snapshot["symbol_notes"]],
            *news_summary["headline_lines"],
        ],
        closing_lines=[
            "What to expect next:",
            f"- {news_summary['expectation']}",
            "- Watch whether overnight cues strengthen or fade the current bias.",
        ],
        link=closing_link,
    )

    news_posts = []
    for idx, alert in enumerate(news_summary["headlines"], start=1):
        alert_link = _rotate_link(f"news-{idx}", generated_at)
        alert_text = "\n".join(
            [
                "Optionthropic News Alert",
                f"Impact: {alert.get('impact_score', 0)}/100",
                f"Headline: {_headline_truncate(alert.get('title') or 'Untitled', limit=120)}",
                "",
                f"Why it matters: {alert.get('impact_reason') or 'Macro risk is rising.'}",
                f"Affected: {', '.join(alert.get('affected_symbols') or []) or 'Broad market'}",
                "",
                f"{alert_link['label']}: {alert_link['url']}",
            ]
        )
        news_posts.append(
            {
                "id": f"news_alert_{idx}",
                "title": f"News Alert #{idx}",
                "text": alert_text,
                "impact_score": alert.get("impact_score", 0),
                "source": alert.get("source"),
                "url": alert.get("url"),
                "link_url": alert_link["url"],
                "link_label": alert_link["label"],
                "bias": bias,
                "probability": probability,
                "context": {
                    "impact_reason": alert.get("impact_reason"),
                    "affected_symbols": alert.get("affected_symbols") or [],
                    "news_url": alert.get("url"),
                },
            }
        )

    return {
        "morning_bias": {
            "title": "Morning Bias",
            "text": morning,
            "bias": bias,
            "probability": probability,
            "impact_score": impact_score,
            "link_url": morning_link["url"],
            "link_label": morning_link["label"],
            "context": {"symbol_notes": bias_snapshot["symbol_notes"]},
        },
        "intraday_update": {
            "title": "Intraday Update",
            "text": intraday,
            "bias": bias,
            "probability": probability,
            "impact_score": impact_score,
            "link_url": intraday_link["url"],
            "link_label": intraday_link["label"],
            "context": {"symbol_notes": bias_snapshot["symbol_notes"]},
        },
        "closing_wrap": {
            "title": "Closing Wrap",
            "text": closing,
            "bias": bias,
            "probability": probability,
            "impact_score": impact_score,
            "link_url": closing_link["url"],
            "link_label": closing_link["label"],
            "context": {"symbol_notes": bias_snapshot["symbol_notes"]},
        },
        "news_alerts": news_posts,
    }


async def _build_live_payload(session: AsyncSession) -> dict[str, Any]:
    from app.alerts.global_news import get_global_news_alerts_payload
    from app.analytics.dashboard_cache import get_dashboard_overview

    overview = await get_dashboard_overview(session)
    news_payload = await get_global_news_alerts_payload(
        session,
        allow_stale=True,
        refresh_if_missing=False,
    )
    generated_at = datetime.now(timezone.utc)
    symbols = overview.get("symbols") or {}
    alerts = list(news_payload.get("alerts") or [])

    bias_snapshot = _market_bias_snapshot(symbols)
    news_summary = _news_summary(alerts)
    posts = _build_posts(
        generated_at=generated_at,
        bias_snapshot=bias_snapshot,
        news_summary=news_summary,
        symbols=symbols,
    )

    return {
        "generated_at": generated_at,
        "generated_at_iso": generated_at.isoformat(),
        "generated_at_ist": to_ist(generated_at).strftime("%Y-%m-%d %H:%M:%S IST"),
        "market_bias": bias_snapshot,
        "news_impact_score": news_summary["impact_score"],
        "news_headlines": [alert.get("title") for alert in news_summary["headlines"]],
        "posts": posts,
    }


def _draft_order_key(row: BroadcastDraft) -> tuple[int, datetime]:
    return (_POST_ORDER.get(row.post_type, 99), row.generated_at)


def _serialize_draft(row: BroadcastDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "channel_type": row.channel_type,
        "post_type": row.post_type,
        "title": row.title,
        "text": row.text,
        "bias": row.bias,
        "probability": row.probability,
        "impact_score": row.impact_score,
        "source": row.source,
        "link_url": row.link_url,
        "link_label": row.link_label,
        "status": row.status.value if isinstance(row.status, BroadcastDraftStatus) else str(row.status),
        "generated_at": row.generated_at.isoformat(),
        "generated_at_ist": to_ist(row.generated_at).strftime("%Y-%m-%d %H:%M:%S IST"),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "context": row.context or {},
    }


def _serialize_batch(batch_id: str, rows: list[BroadcastDraft]) -> dict[str, Any]:
    ordered = sorted(rows, key=_draft_order_key)
    status_counts = {"draft": 0, "approved": 0, "published": 0}
    for row in ordered:
        status_key = row.status.value if isinstance(row.status, BroadcastDraftStatus) else str(row.status)
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

    primary = ordered[0]
    return {
        "batch_id": batch_id,
        "channel_type": primary.channel_type,
        "generated_at": primary.generated_at.isoformat(),
        "generated_at_ist": to_ist(primary.generated_at).strftime("%Y-%m-%d %H:%M:%S IST"),
        "status_counts": status_counts,
        "draft_count": len(ordered),
        "bias": primary.bias,
        "probability": primary.probability,
        "impact_score": primary.impact_score,
        "titles": [row.title for row in ordered],
        "drafts": [_serialize_draft(row) for row in ordered],
    }


def _group_batch_history(rows: list[BroadcastDraft], *, limit: int = 8) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, list[BroadcastDraft]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row.batch_id, []).append(row)

    history: list[dict[str, Any]] = []
    for batch_id, batch_rows in grouped.items():
        history.append(_serialize_batch(batch_id, batch_rows))
        if len(history) >= limit:
            break
    return history


def validate_status_transition(current: str, target: str) -> str:
    normalized = (target or "").strip().lower()
    allowed = {
        BroadcastDraftStatus.DRAFT.value,
        BroadcastDraftStatus.APPROVED.value,
        BroadcastDraftStatus.PUBLISHED.value,
    }
    if normalized not in allowed:
        raise ValueError(f"Unsupported broadcast status: {target}")
    return normalized


def _apply_status(row: BroadcastDraft, *, target_status: str, user_id: str | None, now_utc: datetime) -> None:
    row.status = BroadcastDraftStatus(target_status)
    row.updated_at = now_utc
    if target_status == BroadcastDraftStatus.DRAFT.value:
        row.approved_at = None
        row.approved_by_user_id = None
        row.published_at = None
        row.published_by_user_id = None
        return

    if row.approved_at is None:
        row.approved_at = now_utc
    if user_id:
        row.approved_by_user_id = user_id

    if target_status == BroadcastDraftStatus.PUBLISHED.value:
        row.published_at = now_utc
        if user_id:
            row.published_by_user_id = user_id
    else:
        row.published_at = None
        row.published_by_user_id = None


def _draft_rows_from_payload(
    *,
    batch_id: str,
    channel_type: str,
    payload: dict[str, Any],
    created_by_user_id: str | None,
) -> list[BroadcastDraft]:
    generated_at = payload["generated_at"]
    posts = payload["posts"]
    common_context = {
        "market_bias": payload["market_bias"],
        "news_impact_score": payload["news_impact_score"],
        "news_headlines": payload["news_headlines"],
    }

    rows = [
        BroadcastDraft(
            batch_id=batch_id,
            channel_type=channel_type,
            post_type="MORNING_BIAS",
            title=posts["morning_bias"]["title"],
            text=posts["morning_bias"]["text"],
            bias=posts["morning_bias"]["bias"],
            probability=posts["morning_bias"]["probability"],
            impact_score=posts["morning_bias"]["impact_score"],
            link_url=posts["morning_bias"].get("link_url"),
            link_label=posts["morning_bias"].get("link_label"),
            context={**common_context, **(posts["morning_bias"].get("context") or {})},
            generated_at=generated_at,
            created_by_user_id=created_by_user_id,
        ),
        BroadcastDraft(
            batch_id=batch_id,
            channel_type=channel_type,
            post_type="INTRADAY_UPDATE",
            title=posts["intraday_update"]["title"],
            text=posts["intraday_update"]["text"],
            bias=posts["intraday_update"]["bias"],
            probability=posts["intraday_update"]["probability"],
            impact_score=posts["intraday_update"]["impact_score"],
            link_url=posts["intraday_update"].get("link_url"),
            link_label=posts["intraday_update"].get("link_label"),
            context={**common_context, **(posts["intraday_update"].get("context") or {})},
            generated_at=generated_at,
            created_by_user_id=created_by_user_id,
        ),
        BroadcastDraft(
            batch_id=batch_id,
            channel_type=channel_type,
            post_type="CLOSING_WRAP",
            title=posts["closing_wrap"]["title"],
            text=posts["closing_wrap"]["text"],
            bias=posts["closing_wrap"]["bias"],
            probability=posts["closing_wrap"]["probability"],
            impact_score=posts["closing_wrap"]["impact_score"],
            link_url=posts["closing_wrap"].get("link_url"),
            link_label=posts["closing_wrap"].get("link_label"),
            context={**common_context, **(posts["closing_wrap"].get("context") or {})},
            generated_at=generated_at,
            created_by_user_id=created_by_user_id,
        ),
    ]

    for alert in posts["news_alerts"]:
        rows.append(
            BroadcastDraft(
                batch_id=batch_id,
                channel_type=channel_type,
                post_type="NEWS_ALERT",
                title=alert["title"],
                text=alert["text"],
                bias=alert.get("bias"),
                probability=alert.get("probability"),
                impact_score=_safe_int(alert.get("impact_score")),
                source=alert.get("source"),
                link_url=alert.get("link_url"),
                link_label=alert.get("link_label"),
                context={**common_context, **(alert.get("context") or {})},
                generated_at=generated_at,
                created_by_user_id=created_by_user_id,
            )
        )

    return rows


async def generate_broadcast_batch(
    session: AsyncSession,
    *,
    channel_type: str = "WHATSAPP",
    created_by_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_channel = _normalize_channel_type(channel_type)
    payload = await _build_live_payload(session)
    batch_id = str(uuid.uuid4())
    rows = _draft_rows_from_payload(
        batch_id=batch_id,
        channel_type=normalized_channel,
        payload=payload,
        created_by_user_id=created_by_user_id,
    )
    session.add_all(rows)
    await session.flush()

    return {
        "channel_type": normalized_channel,
        "live_preview": {
            "generated_at": payload["generated_at_iso"],
            "generated_at_ist": payload["generated_at_ist"],
            "market_bias": payload["market_bias"],
            "news_impact_score": payload["news_impact_score"],
            "news_headlines": payload["news_headlines"],
        },
        "current_batch": _serialize_batch(batch_id, rows),
    }


async def get_broadcast_workspace(
    session: AsyncSession,
    *,
    channel_type: str = "WHATSAPP",
    auto_generate: bool = True,
    created_by_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_channel = _normalize_channel_type(channel_type)
    stmt = (
        select(BroadcastDraft)
        .where(BroadcastDraft.channel_type == normalized_channel)
        .order_by(desc(BroadcastDraft.generated_at), desc(BroadcastDraft.created_at))
        .limit(80)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    current_batch: dict[str, Any] | None = None
    live_preview: dict[str, Any] | None = None
    if not rows and auto_generate:
        generated = await generate_broadcast_batch(
            session,
            channel_type=normalized_channel,
            created_by_user_id=created_by_user_id,
        )
        current_batch = generated["current_batch"]
        live_preview = generated["live_preview"]
        rows = list((await session.execute(stmt)).scalars().all())

    history = _group_batch_history(rows, limit=10)
    if history and current_batch is None:
        current_batch = history[0]

    if live_preview is None:
        if current_batch:
            live_preview = {
                "generated_at": current_batch["generated_at"],
                "generated_at_ist": current_batch["generated_at_ist"],
                "market_bias": {
                    "bias": current_batch.get("bias"),
                    "probability": current_batch.get("probability"),
                },
                "news_impact_score": current_batch.get("impact_score"),
                "news_headlines": current_batch.get("titles", []),
            }
        else:
            live_preview = {
                "generated_at": None,
                "generated_at_ist": None,
                "market_bias": {"bias": "Neutral", "probability": 50},
                "news_impact_score": 0,
                "news_headlines": [],
            }

    return {
        "channel_type": normalized_channel,
        "live_preview": live_preview,
        "current_batch": current_batch,
        "history": history,
    }


async def update_broadcast_draft_status(
    session: AsyncSession,
    *,
    draft_id: str,
    status: str,
    current_user_id: str | None,
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(BroadcastDraft).where(BroadcastDraft.id == draft_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Broadcast draft not found")

    normalized_status = validate_status_transition(
        row.status.value if isinstance(row.status, BroadcastDraftStatus) else str(row.status),
        status,
    )
    _apply_status(
        row,
        target_status=normalized_status,
        user_id=current_user_id,
        now_utc=datetime.now(timezone.utc),
    )
    await session.flush()
    return _serialize_draft(row)


async def build_broadcast_desk_payload(session: AsyncSession) -> dict[str, Any]:
    payload = await _build_live_payload(session)
    return {
        "generated_at": payload["generated_at_iso"],
        "generated_at_ist": payload["generated_at_ist"],
        "market_bias": payload["market_bias"],
        "news_impact_score": payload["news_impact_score"],
        "news_headlines": payload["news_headlines"],
        "posts": payload["posts"],
    }
