"""
Pure parsing and scoring helpers for critical global-news alerts.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

TRUSTED_SOURCES = {
    "reuters",
    "bloomberg",
    "financial times",
    "wall street journal",
    "cnbc",
    "federal reserve",
    "reserve bank of india",
    "rbi",
}


@dataclass(slots=True)
class NewsCandidate:
    provider: str
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class ImpactRule:
    name: str
    keywords: tuple[str, ...]
    weight: int
    symbols: tuple[str, ...]


IMPACT_RULES: tuple[ImpactRule, ...] = (
    ImpactRule(
        name="Central banks and rates",
        keywords=("federal reserve", "fomc", "powell", "rbi", "ecb", "boj", "boe", "rate hike", "rate cut"),
        weight=34,
        symbols=("NIFTY", "BANKNIFTY", "SENSEX", "GOLD", "SILVER"),
    ),
    ImpactRule(
        name="Inflation and growth data",
        keywords=("inflation", "cpi", "pce", "ppi", "payroll", "jobs report", "gdp", "recession"),
        weight=28,
        symbols=("NIFTY", "BANKNIFTY", "SENSEX", "GOLD", "SILVER"),
    ),
    ImpactRule(
        name="Oil and energy shock",
        keywords=("oil", "crude", "brent", "opec", "energy shock", "middle east"),
        weight=28,
        symbols=("CRUDEOIL", "NATGAS", "NIFTY", "SENSEX"),
    ),
    ImpactRule(
        name="Banking and credit risk",
        keywords=("bank crisis", "banking stress", "credit event", "liquidity crunch", "default", "treasury yield", "bond yield"),
        weight=34,
        symbols=("BANKNIFTY", "NIFTY", "SENSEX"),
    ),
    ImpactRule(
        name="Geopolitics and sanctions",
        keywords=("war", "sanctions", "tariff", "conflict", "missile", "shipping disruption"),
        weight=24,
        symbols=("CRUDEOIL", "GOLD", "SILVER", "NIFTY", "SENSEX"),
    ),
    ImpactRule(
        name="India and FX sensitivity",
        keywords=("rupee", "usdinr", "india markets", "india economy", "china stimulus", "asia markets"),
        weight=18,
        symbols=("NIFTY", "BANKNIFTY", "SENSEX"),
    ),
)


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", unescape(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s*-\s*[^-]+$", "", title or "").strip().lower()


def dedupe_key(title: str, source: str, published_at: datetime | None) -> str:
    published = published_at.isoformat() if published_at else ""
    raw = f"{_normalize_title(title)}|{source.strip().lower()}|{published[:13]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _rss_children_text(item: ET.Element, name: str) -> str | None:
    for child in item:
        if child.tag.split("}")[-1].lower() == name.lower():
            return (child.text or "").strip()
    return None


def parse_rss_items(xml_text: str) -> list[NewsCandidate]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    out: list[NewsCandidate] = []
    for item in root.findall(".//item"):
        title = _rss_children_text(item, "title") or ""
        if not title:
            continue
        source = _rss_children_text(item, "source") or "Unknown"
        summary = _strip_html(_rss_children_text(item, "description"))
        out.append(
            NewsCandidate(
                provider="rss",
                source=source,
                title=title,
                summary=summary,
                url=_rss_children_text(item, "link") or "",
                published_at=safe_pubdate(_rss_children_text(item, "pubDate")),
            )
        )
    return out


def score_news_candidate(candidate: NewsCandidate, now_utc: datetime | None = None) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    text = f"{candidate.title} {candidate.summary}".lower()
    score = 0
    themes: list[str] = []
    affected: set[str] = set()

    for rule in IMPACT_RULES:
        if any(keyword in text for keyword in rule.keywords):
            score += rule.weight
            themes.append(rule.name)
            affected.update(rule.symbols)

    source_lc = candidate.source.lower()
    if any(trusted in source_lc for trusted in TRUSTED_SOURCES):
        score += 10
        themes.append("Trusted source")

    if ("federal reserve" in text or "fomc" in text or "rbi" in text) and (
        "rate cut" in text or "rate hike" in text or "inflation" in text or "cpi" in text
    ):
        score += 16
        themes.append("Policy catalyst")

    if "oil" in text and ("opec" in text or "supply cut" in text or "middle east" in text):
        score += 22
        themes.append("Direct commodity shock")

    if "bank crisis" in text or "liquidity crunch" in text or "default" in text:
        score += 20
        themes.append("Systemic risk")

    if candidate.published_at is not None:
        age = max((now - candidate.published_at).total_seconds(), 0)
        if age <= 2 * 3600:
            score += 10
            themes.append("Fresh headline")
        elif age <= 6 * 3600:
            score += 5

    if any(token in text for token in ("bank", "lender", "nbfc", "credit")):
        affected.add("BANKNIFTY")
    if any(token in text for token in ("oil", "crude", "brent", "rupee", "usdinr", "tariff", "export")):
        affected.update(("NIFTY", "SENSEX"))
    if any(token in text for token in ("oil", "crude", "brent", "opec", "refinery")):
        affected.add("CRUDEOIL")
    if any(token in text for token in ("natural gas", "natgas", "lng", "gas supply")):
        affected.add("NATGAS")
    if any(token in text for token in ("fomc", "federal reserve", "inflation", "cpi", "payroll", "rbi")):
        affected.update(("NIFTY", "BANKNIFTY", "SENSEX"))
    if any(token in text for token in ("gold", "silver", "bullion", "treasury yield", "bond yield", "safe haven")):
        affected.update(("GOLD", "SILVER"))
    if any(token in text for token in ("inflation", "cpi", "federal reserve", "rbi", "rate cut", "rate hike")):
        affected.update(("GOLD", "SILVER"))

    score = min(score, 100)
    if score >= 85:
        move_potential = "VERY_HIGH"
        severity = "HIGH"
    elif score >= 70:
        move_potential = "HIGH"
        severity = "HIGH"
    elif score >= 55:
        move_potential = "WATCH"
        severity = "MEDIUM"
    else:
        move_potential = "IGNORE"
        severity = "INFO"

    if not affected and score >= 55:
        affected.update(("NIFTY", "BANKNIFTY", "SENSEX"))

    critical = score >= 70
    reason = " + ".join(dict.fromkeys(themes)) or "Low macro relevance"
    return {
        "impact_score": score,
        "move_potential": move_potential,
        "severity": severity,
        "affected_symbols": sorted(affected),
        "matched_themes": themes,
        "impact_reason": reason,
        "is_critical": critical,
        "dedupe_key": dedupe_key(candidate.title, candidate.source, candidate.published_at),
    }
