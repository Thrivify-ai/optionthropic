"""
AI-powered market explainer.

Builds a structured context snapshot from the latest analytics for a symbol
and generates a plain-language insight using OpenAI GPT-4o or Anthropic Claude.

Results are cached in-process for AI_CACHE_TTL_SECONDS (default 5 min) to
minimise API costs during high-traffic periods.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.global_news import list_recent_global_news_alerts
from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.liquidity_trap_detection import detect_liquidity_traps
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr, compute_support_resistance
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.positioning_shift import detect_positioning_shifts
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.market_summary_cache import MarketSummaryCache
from app.services.market_hours import ai_cache_ttl_seconds, should_refresh_intraday_caches
from app.services.runtime_cache import runtime_cache

logger = get_logger(__name__)
MARKET_SUMMARY_CACHE_KEY_PREFIX = "market-summary"

# ─── Simple in-process cache ───────────────────────────────────────────────────
_cache: dict[str, tuple[float, str]] = {}
_refresh_inflight: set[str] = set()


def _get_cached(symbol: str) -> str | None:
    if symbol in _cache:
        ts, value = _cache[symbol]
        if time.monotonic() - ts < ai_cache_ttl_seconds():
            return value
    return None


def _set_cache(symbol: str, value: str) -> None:
    _cache[symbol] = (time.monotonic(), value)


def _has_ai_credentials() -> bool:
    return bool(
        settings.openai_api_key
        or settings.anthropic_api_key
        or (settings.ai_provider == "bedrock" and settings.aws_access_key_id)
    )


async def get_cached_market_summary_row(session: AsyncSession, symbol: str) -> MarketSummaryCache | None:
    row = await session.get(MarketSummaryCache, symbol)
    if row is None or row.generated_at is None:
        return None

    generated_at = row.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - generated_at > timedelta(seconds=ai_cache_ttl_seconds()):
        return None
    return row


async def get_latest_market_summary_row(session: AsyncSession, symbol: str) -> MarketSummaryCache | None:
    return await session.get(MarketSummaryCache, symbol)


def _market_summary_cache_key(symbol: str) -> str:
    return f"{MARKET_SUMMARY_CACHE_KEY_PREFIX}:{symbol}:v1"


def _summary_payload(
    symbol: str,
    insight: str,
    *,
    cached: bool,
    pending: bool = False,
    generated_at: datetime | None = None,
    stale: bool = False,
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "insight": insight,
        "cached": cached,
        "pending": pending,
        "generated_at": generated_at.isoformat() if generated_at else None,
    }
    if stale:
        payload["stale"] = True
    return payload


async def _cache_market_summary_payload(symbol: str, payload: dict[str, Any], now_utc: datetime | None = None) -> None:
    await runtime_cache.set_json(
        _market_summary_cache_key(symbol),
        payload,
        ttl_seconds=ai_cache_ttl_seconds(now_utc),
    )


async def _persist_market_summary(
    session: AsyncSession,
    symbol: str,
    insight: str,
    source_timestamp: datetime | None = None,
) -> None:
    row = await session.get(MarketSummaryCache, symbol)
    model_id = settings.bedrock_model_id if settings.ai_provider == "bedrock" else settings.ai_provider
    if row is None:
        session.add(
            MarketSummaryCache(
                symbol=symbol,
                insight=insight,
                provider=settings.ai_provider,
                model_id=model_id,
                cached=True,
                source_timestamp=source_timestamp,
                generated_at=datetime.now(timezone.utc),
            )
        )
    else:
        row.insight = insight
        row.provider = settings.ai_provider
        row.model_id = model_id
        row.cached = True
        row.source_timestamp = source_timestamp
        row.generated_at = datetime.now(timezone.utc)


# ─── Prompt builder ────────────────────────────────────────────────────────────


async def _safe_analytics_call(fn: Any, session: AsyncSession, symbol: str) -> Any:
    try:
        return await fn(session, symbol)
    except Exception as exc:
        logger.warning(
            "Market explainer analytics call failed",
            symbol=symbol,
            fn=getattr(fn, "__name__", "unknown"),
            error=str(exc),
        )
        return {}


async def _build_context(session: AsyncSession, symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "critical_news": await list_recent_global_news_alerts(session, symbols=[symbol], limit=3),
        "pcr": await _safe_analytics_call(compute_pcr, session, symbol),
        "support_resistance": await _safe_analytics_call(compute_support_resistance, session, symbol),
        "gamma_walls": await _safe_analytics_call(compute_gamma_walls, session, symbol),
        "max_pain": await _safe_analytics_call(compute_max_pain, session, symbol),
        "options_flow": await _safe_analytics_call(detect_options_flow, session, symbol),
        "positioning_shift": await _safe_analytics_call(detect_positioning_shifts, session, symbol),
        "liquidity_traps": await _safe_analytics_call(detect_liquidity_traps, session, symbol),
    }


def _format_prompt(ctx: dict[str, Any]) -> str:
    symbol = ctx["symbol"]
    pcr = ctx.get("pcr", {})
    gw = ctx.get("gamma_walls", {})
    mp = ctx.get("max_pain", {})
    sr = ctx.get("support_resistance", {})
    ps = ctx.get("positioning_shift", {})
    flow = ctx.get("options_flow", {})
    traps = ctx.get("liquidity_traps", {})
    critical_news = ctx.get("critical_news", [])[:3]

    top_resistance = sr.get("resistance", [{}])[:2]
    top_support = sr.get("support", [{}])[:2]
    top_flows = flow.get("flows", [])[:3]
    top_shifts = ps.get("shifts", [])[:3]
    trap_list = traps.get("traps", [])[:3]
    top_news = [
        f"{item.get('title')} (impact {item.get('impact_score', 0)}, source {item.get('source', 'Unknown')})"
        for item in critical_news
        if item.get("title")
    ]

    prompt = f"""You are a senior derivatives market analyst specialising in Indian equity index options (NSE/BSE).

Analyse the following real-time options data for {symbol} and generate a 3–4 sentence plain-language market insight.
Focus on institutional positioning, key levels, and near-term directional bias.
Be specific with strike prices and write in professional but accessible language.

=== MARKET DATA ===
Underlying: {gw.get('underlying_price', 'N/A')}

PCR (OI): {pcr.get('pcr_oi', 'N/A')} | PCR (Volume): {pcr.get('pcr_volume', 'N/A')} | Sentiment: {pcr.get('sentiment', 'N/A')}

Gamma Walls:
  Call Wall: {gw.get('call_wall', 'N/A')}
  Put Wall: {gw.get('put_wall', 'N/A')}

Max Pain: {mp.get('max_pain_strike', 'N/A')} (spot deviation: {mp.get('deviation_from_spot_pct', 'N/A')}%)

Key Resistance: {[f"{r.get('strike')} (call OI {r.get('call_oi',0):,})" for r in top_resistance]}
Key Support: {[f"{s.get('strike')} (put OI {s.get('put_oi',0):,})" for s in top_support]}

Top Positioning Shifts: {[f"Strike {s.get('strike')}: {s.get('call_signal')}/{s.get('put_signal')}" for s in top_shifts]}

Smart Money Flow: {[f"{f.get('flow_type')} {f.get('option_type')} at {f.get('strike')} vol={f.get('volume',0):,}" for f in top_flows]}

Liquidity Traps: {[f"Strike {t.get('strike')} ({t.get('side')})" for t in trap_list]}
Critical Global News: {top_news or ['No major macro headline']}

=== INSTRUCTION ===
Generate a 3–4 sentence market insight. Example format:
"Put writers are aggressively defending the 22100 level while call writers have built significant positions at 22300, suggesting a 22100–22300 range. The PCR of 1.2 indicates a mild bullish bias. A break above 22300 could trigger a short-covering rally toward 22500."
"""
    return prompt


# ─── AI providers ──────────────────────────────────────────────────────────────

async def _call_openai(prompt: str) -> str:
    import openai  # type: ignore[import]

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=180,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


async def _call_anthropic(prompt: str) -> str:
    import anthropic  # type: ignore[import]

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=180,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


async def _call_bedrock(prompt: str) -> str:
    """
    Calls AWS Bedrock using the Converse API.
    Works with Claude, Llama, Titan and all other Bedrock models
    through a single unified interface.
    """
    import json
    import asyncio
    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )

    messages = [{"role": "user", "content": [{"text": prompt}]}]

    def _invoke():
        return client.converse(
            modelId=settings.bedrock_model_id,
            messages=messages,
            inferenceConfig={"maxTokens": 180, "temperature": 0.3},
        )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, _invoke)

    output = response["output"]["message"]["content"]
    return "".join(block.get("text", "") for block in output).strip()


async def _generate_insight(prompt: str) -> str:
    provider = settings.ai_provider

    _provider_map = {
        "openai": _call_openai,
        "anthropic": _call_anthropic,
        "bedrock": _call_bedrock,
    }
    _fallback_order = {
        "openai": [_call_openai, _call_bedrock, _call_anthropic],
        "anthropic": [_call_anthropic, _call_bedrock, _call_openai],
        "bedrock": [_call_bedrock, _call_anthropic, _call_openai],
    }

    for fn in _fallback_order.get(provider, [_call_bedrock]):
        try:
            return await fn(prompt)
        except Exception as exc:
            logger.warning(
                "AI provider call failed, trying next",
                provider=fn.__name__,
                error=str(exc),
            )

    logger.error("All AI providers failed")
    return "AI insight temporarily unavailable."


async def refresh_market_summary_cache(session: AsyncSession, symbol: str) -> dict[str, Any]:
    ctx = await _build_context(session, symbol)
    prompt = _format_prompt(ctx)
    insight = await _generate_insight(prompt)
    await _persist_market_summary(session, symbol, insight)
    _set_cache(symbol, insight)
    payload = _summary_payload(
        symbol,
        insight,
        cached=False,
        generated_at=datetime.now(timezone.utc),
    )
    await _cache_market_summary_payload(symbol, payload)
    return payload


async def get_market_summary_payload(
    session: AsyncSession,
    symbol: str,
    *,
    allow_stale: bool,
    refresh_if_missing: bool,
) -> dict[str, Any]:
    shared = await runtime_cache.get_json(_market_summary_cache_key(symbol))
    if isinstance(shared, dict) and shared.get("insight"):
        return shared

    db_cached = await get_cached_market_summary_row(session, symbol)
    if db_cached is not None:
        payload = _summary_payload(
            symbol,
            db_cached.insight,
            cached=True,
            generated_at=db_cached.generated_at,
        )
        _set_cache(symbol, db_cached.insight)
        await _cache_market_summary_payload(symbol, payload)
        return payload

    latest = await get_latest_market_summary_row(session, symbol)
    if allow_stale and latest is not None:
        payload = _summary_payload(
            symbol,
            latest.insight,
            cached=True,
            generated_at=latest.generated_at,
            stale=True,
        )
        _set_cache(symbol, latest.insight)
        await _cache_market_summary_payload(symbol, payload)
        return payload

    cached = _get_cached(symbol)
    if cached:
        payload = _summary_payload(symbol, cached, cached=True)
        await _cache_market_summary_payload(symbol, payload)
        return payload

    if should_refresh_intraday_caches():
        if not _has_ai_credentials():
            return {
                "symbol": symbol,
                "insight": "AI market explanation requires API credentials (OpenAI, Anthropic, or AWS Bedrock).",
                "cached": False,
                "pending": False,
                "generated_at": None,
            }
        import asyncio

        if refresh_if_missing:
            asyncio.create_task(trigger_market_summary_refresh(symbol))
        return {
            "symbol": symbol,
            "insight": "Generating cached market insight...",
            "cached": False,
            "pending": True,
            "generated_at": None,
        }

    return {
        "symbol": symbol,
        "insight": "No cached market insight available.",
        "cached": False,
        "pending": False,
        "generated_at": None,
    }


async def warm_market_summary_shared_cache() -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        for symbol in settings.supported_symbols:
            row = await get_latest_market_summary_row(session, symbol)
            if row is None:
                continue
            payload = _summary_payload(
                symbol,
                row.insight,
                cached=True,
                generated_at=row.generated_at,
                stale=(not should_refresh_intraday_caches(now)),
            )
            _set_cache(symbol, row.insight)
            await _cache_market_summary_payload(symbol, payload, now)


async def trigger_market_summary_refresh(symbol: str) -> None:
    if not _has_ai_credentials() or symbol in _refresh_inflight or not should_refresh_intraday_caches():
        return

    _refresh_inflight.add(symbol)
    async with AsyncSessionLocal() as session:
        try:
            await refresh_market_summary_cache(session, symbol)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("Background market summary refresh failed", symbol=symbol, error=str(exc))
        finally:
            _refresh_inflight.discard(symbol)


# ─── Public interface ──────────────────────────────────────────────────────────

async def explain_market(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """Return cached or freshly generated AI market insight for `symbol`."""
    market_open = should_refresh_intraday_caches()
    return await get_market_summary_payload(
        session,
        symbol,
        allow_stale=not market_open,
        refresh_if_missing=market_open,
    )
