from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class QuantSignalOutcome(Base):
    __tablename__ = "quant_signal_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # QUICK | MAIN
    signal_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    outlook: Mapped[str | None] = mapped_column(String(12), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session_bucket: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    vol_regime: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    breakout_class: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    expiry_bucket: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    regime_label: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    days_to_expiry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_expiry_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    open_gap_pct: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    data_freshness_seconds: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    snapshot_spacing_std_seconds: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    short_covering_risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trap_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_shift_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    selected_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    selected_strike: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    selected_option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    selected_contract_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)

    underlying_entry_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    option_entry_ltp: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    underlying_price_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_price_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_price_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_price_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_price_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    option_price_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_price_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_price_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_price_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_price_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    underlying_move_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_move_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_move_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_move_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underlying_move_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    option_move_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_move_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_move_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_move_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_move_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    underlying_outcome_2m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    underlying_outcome_3m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    underlying_outcome_5m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    underlying_outcome_10m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    underlying_outcome_30m: Mapped[str | None] = mapped_column(String(16), nullable=True)

    option_outcome_2m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    option_outcome_3m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    option_outcome_5m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    option_outcome_10m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    option_outcome_30m: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
