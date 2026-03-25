"""
Shared persistence helpers for raw option-chain snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.models.options_snapshot import OptionsSnapshot


async def persist_chain_snapshots(
    session: AsyncSession,
    symbol: str,
    records: list[dict],
    *,
    default_timestamp: datetime | None = None,
) -> datetime | None:
    if not records:
        return None

    fallback_timestamp = default_timestamp or datetime.now(timezone.utc)
    snapshots = []
    chain_map: dict[tuple, dict] = {}
    latest_timestamp: datetime | None = None

    for record in records:
        row_timestamp = record.get("source_timestamp") or fallback_timestamp
        if latest_timestamp is None or row_timestamp > latest_timestamp:
            latest_timestamp = row_timestamp

        snapshots.append(
            OptionsSnapshot(
                symbol=record["symbol"],
                strike=record["strike"],
                expiry=record["expiry"],
                option_type=record["option_type"],
                oi=record["oi"],
                volume=record["volume"],
                last_price=record["last_price"],
                underlying_price=record["underlying_price"],
                timestamp=row_timestamp,
            )
        )

        key = (record["strike"], record["expiry"], row_timestamp)
        if key not in chain_map:
            chain_map[key] = {
                "symbol": symbol,
                "strike": record["strike"],
                "expiry": record["expiry"],
                "call_oi": 0,
                "put_oi": 0,
                "call_volume": 0,
                "put_volume": 0,
                "underlying_price": record["underlying_price"],
                "timestamp": row_timestamp,
            }

        if record["option_type"] == "CE":
            chain_map[key]["call_oi"] += record["oi"]
            chain_map[key]["call_volume"] += record["volume"]
        else:
            chain_map[key]["put_oi"] += record["oi"]
            chain_map[key]["put_volume"] += record["volume"]

    session.add_all(snapshots)
    for data in chain_map.values():
        session.add(ChainSnapshot(**data))

    await session.flush()
    return latest_timestamp
