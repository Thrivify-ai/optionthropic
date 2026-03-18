"""
AI-powered market explainer.

Builds a structured context snapshot from the latest analytics for a symbol
and generates a plain-language insight using OpenAI GPT-4o or Anthropic Claude.

Results are cached in-process for AI_CACHE_TTL_SECONDS (default 5 min) to
minimise API costs during high-traffic periods.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.liquidity_trap_detection import detect_liquidity_traps
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr, compute_support_resistance
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.positioning_shift import detect_positioning_shifts
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# ─── Simple in-process cache ───────────────────────────────────────────────────
_cache: dict[str, tuple[float, str]] = {}


def _get_cached(symbol: str) -> str | None:
    if symbol in _cache:
        ts, value = _cache[symbol]
        if time.monotonic() - ts < settings.ai_cache_ttl_seconds:
            return value
    return None


def _set_cache(symbol: str, value: str) -> None:
    _cache[symbol] = (time.monotonic(), value)


# ─── Prompt builder ────────────────────────────────────────────────────────────


async def _build_context(session: AsyncSession, symbol: str) -> dict[str, Any]:
    pcr_task = compute_pcr(session, symbol)
    sr_task = compute_support_resistance(session, symbol)
    gw_task = compute_gamma_walls(session, symbol)
    mp_task = compute_max_pain(session, symbol)
    flow_task = detect_options_flow(session, symbol)
    ps_task = detect_positioning_shifts(session, symbol)
    lt_task = detect_liquidity_traps(session, symbol)

    import asyncio
    results = await asyncio.gather(
        pcr_task, sr_task, gw_task, mp_task, flow_task, ps_task, lt_task,
        return_exceptions=True,
    )

    def safe(r: Any) -> Any:
        return r if not isinstance(r, Exception) else {}

    return {
        "symbol": symbol,
        "pcr": safe(results[0]),
        "support_resistance": safe(results[1]),
        "gamma_walls": safe(results[2]),
        "max_pain": safe(results[3]),
        "options_flow": safe(results[4]),
        "positioning_shift": safe(results[5]),
        "liquidity_traps": safe(results[6]),
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

    top_resistance = sr.get("resistance", [{}])[:2]
    top_support = sr.get("support", [{}])[:2]
    top_flows = flow.get("flows", [])[:3]
    top_shifts = ps.get("shifts", [])[:3]
    trap_list = traps.get("traps", [])[:3]

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
        max_tokens=300,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


async def _call_anthropic(prompt: str) -> str:
    import anthropic  # type: ignore[import]

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=300,
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
            inferenceConfig={"maxTokens": 300, "temperature": 0.4},
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


# ─── Public interface ──────────────────────────────────────────────────────────

async def explain_market(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """Return cached or freshly generated AI market insight for `symbol`."""
    cached = _get_cached(symbol)
    if cached:
        return {"symbol": symbol, "insight": cached, "cached": True}

    has_credentials = (
        settings.openai_api_key
        or settings.anthropic_api_key
        or (settings.ai_provider == "bedrock" and settings.aws_access_key_id)
    )
    if not has_credentials:
        return {
            "symbol": symbol,
            "insight": "AI market explanation requires API credentials (OpenAI, Anthropic, or AWS Bedrock).",
            "cached": False,
        }

    try:
        ctx = await _build_context(session, symbol)
        prompt = _format_prompt(ctx)
        insight = await _generate_insight(prompt)
        _set_cache(symbol, insight)
        return {"symbol": symbol, "insight": insight, "cached": False}
    except Exception as exc:
        logger.error("Market explainer failed", symbol=symbol, error=str(exc))
        return {"symbol": symbol, "insight": "Unable to generate market insight at this time.", "cached": False}
