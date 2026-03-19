from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SignalFeatureSnapshot(Base):
    __tablename__ = "signal_feature_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    snapshot_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    current_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    prev_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    price_change_points: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    price_change_pct: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)

    total_call_oi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_put_oi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_call_oi_prev: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_put_oi_prev: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pcr_oi: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    support_strike: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    resistance_strike: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    near_support_put_oi_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    near_resistance_call_oi_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    writer_bullish_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    writer_bearish_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position_buildup: Mapped[str | None] = mapped_column(String(30), nullable=True)

    volume_spike: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_rangebound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rangebound_oi_both_sides: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breakout_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breakdown_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trap_warning_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
