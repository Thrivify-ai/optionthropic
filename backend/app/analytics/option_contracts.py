"""
Representative option-contract selection for calibration.

We keep this intentionally deterministic so historical calibration replays the
same contract choice every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Iterable

from app.services.market_hours import to_ist

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.options_snapshot import OptionsSnapshot

_DEFAULT_LOOKUP_WINDOW = timedelta(minutes=20)


@dataclass
class SelectedOptionContract:
    expiry: date | None
    strike: float | None
    option_type: str | None
    last_price: float | None
    quality: str | None
    snapshot_time: datetime | None


def contract_type_for_signal(signal: str) -> str | None:
    if signal == "Buy CE":
        return "CE"
    if signal == "Buy PE":
        return "PE"
    return None


def _strike_step(rows: Iterable[OptionsSnapshot]) -> float:
    strikes = sorted({float(row.strike) for row in rows})
    steps = [round(curr - prev, 2) for prev, curr in zip(strikes, strikes[1:]) if curr > prev]
    return min(steps) if steps else 0.0


def _pick_expiry(expiries: list[date], entry_time: datetime, engine: str) -> date | None:
    if not expiries:
        return None
    now_ist = to_ist(entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc))
    same_day = expiries[0] == now_ist.date()
    if same_day and len(expiries) > 1:
        if engine.upper() == "MAIN" and now_ist.time().hour >= 13:
            return expiries[1]
        if engine.upper() == "QUICK" and now_ist.time().hour >= 14:
            return expiries[1]
    return expiries[0]


def _quality(oi: int, volume: int, ltp: float | None) -> str:
    if ltp is None:
        return "LOW"
    if oi >= 10000 and volume >= 5000 and ltp >= 20:
        return "HIGH"
    if oi >= 2500 and volume >= 1000 and ltp >= 10:
        return "MEDIUM"
    return "LOW"


async def _load_snapshot_rows(
    session: AsyncSession,
    symbol: str,
    option_type: str,
    entry_time: datetime,
    *,
    window: timedelta = _DEFAULT_LOOKUP_WINDOW,
) -> tuple[datetime | None, list[OptionsSnapshot]]:
    from sqlalchemy import desc, select
    from app.models.instruments import OptionType
    from app.models.options_snapshot import OptionsSnapshot

    reference = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
    option_type_enum = OptionType(option_type)
    timestamps = (
        await session.execute(
            select(OptionsSnapshot.timestamp)
            .where(
                OptionsSnapshot.symbol == symbol,
                OptionsSnapshot.option_type == option_type_enum,
                OptionsSnapshot.timestamp >= reference - window,
                OptionsSnapshot.timestamp <= reference + window,
            )
            .distinct()
            .order_by(desc(OptionsSnapshot.timestamp))
            .limit(20)
        )
    ).scalars().all()
    if not timestamps:
        return None, []

    target_ts = reference.timestamp()
    best_ts = min(
        timestamps,
        key=lambda ts: abs((ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp() - target_ts),
    )
    rows = (
        await session.execute(
            select(OptionsSnapshot)
            .where(
                OptionsSnapshot.symbol == symbol,
                OptionsSnapshot.option_type == option_type_enum,
                OptionsSnapshot.timestamp == best_ts,
            )
            .order_by(OptionsSnapshot.expiry.asc(), OptionsSnapshot.strike.asc())
        )
    ).scalars().all()
    return best_ts, rows


async def select_option_contract(
    session: AsyncSession,
    *,
    symbol: str,
    signal: str,
    entry_time: datetime,
    spot_price: float | None,
    engine: str,
) -> SelectedOptionContract:
    option_type = contract_type_for_signal(signal)
    if option_type is None or not spot_price:
        return SelectedOptionContract(None, None, None, None, None, None)

    snapshot_time, rows = await _load_snapshot_rows(session, symbol, option_type, entry_time)
    if not rows:
        return SelectedOptionContract(None, None, option_type, None, None, snapshot_time)

    expiries = sorted({row.expiry for row in rows})
    selected_expiry = _pick_expiry(expiries, entry_time, engine)
    expiry_rows = [row for row in rows if row.expiry == selected_expiry] if selected_expiry else []
    if not expiry_rows:
        return SelectedOptionContract(selected_expiry, None, option_type, None, None, snapshot_time)

    step = _strike_step(expiry_rows)
    atm_row = min(expiry_rows, key=lambda row: abs(float(row.strike) - float(spot_price)))
    target_strike = float(atm_row.strike)

    current_ist = to_ist(entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc))
    prefer_itm = engine.upper() == "MAIN" or (selected_expiry == current_ist.date() and current_ist.time().hour >= 13)
    if prefer_itm and step > 0:
        if signal == "Buy CE":
            target_strike = target_strike - step
        elif signal == "Buy PE":
            target_strike = target_strike + step

    picked = min(expiry_rows, key=lambda row: abs(float(row.strike) - target_strike))
    ltp = float(picked.last_price) if picked.last_price is not None else None
    return SelectedOptionContract(
        expiry=picked.expiry,
        strike=float(picked.strike),
        option_type=option_type,
        last_price=ltp,
        quality=_quality(int(picked.oi or 0), int(picked.volume or 0), ltp),
        snapshot_time=snapshot_time,
    )


async def option_price_at_time(
    session: AsyncSession,
    *,
    symbol: str,
    contract: SelectedOptionContract,
    target: datetime,
    tolerance_minutes: int,
) -> float | None:
    from sqlalchemy import desc, select
    from app.models.instruments import OptionType
    from app.models.options_snapshot import OptionsSnapshot

    if (
        contract.expiry is None
        or contract.strike is None
        or contract.option_type is None
    ):
        return None

    option_type = OptionType(contract.option_type)
    window = timedelta(minutes=tolerance_minutes)
    reference = target if target.tzinfo else target.replace(tzinfo=timezone.utc)
    rows = (
        await session.execute(
            select(OptionsSnapshot.last_price, OptionsSnapshot.timestamp)
            .where(
                OptionsSnapshot.symbol == symbol,
                OptionsSnapshot.expiry == contract.expiry,
                OptionsSnapshot.strike == contract.strike,
                OptionsSnapshot.option_type == option_type,
                OptionsSnapshot.timestamp >= reference - window,
                OptionsSnapshot.timestamp <= reference + window,
            )
            .order_by(desc(OptionsSnapshot.timestamp))
            .limit(40)
        )
    ).all()
    if not rows:
        return None

    target_ts = reference.timestamp()
    best_price = None
    best_diff = float("inf")
    for price, ts in rows:
        if price is None or ts is None:
            continue
        comp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        diff = abs(comp.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_price = float(price)
    return best_price
