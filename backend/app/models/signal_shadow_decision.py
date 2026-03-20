from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SignalShadowDecision(Base):
    __tablename__ = "signal_shadow_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    signal_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False, index=True)  # LIVE | SHADOW
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    outlook: Mapped[str | None] = mapped_column(String(12), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session_bucket: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vol_regime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    breakout_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    expiry_bucket: Mapped[str | None] = mapped_column(String(16), nullable=True)
    regime_label: Mapped[str | None] = mapped_column(String(20), nullable=True)

    days_to_expiry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_freshness_seconds: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    snapshot_spacing_std_seconds: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    short_covering_risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trap_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_shift_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=datetime.utcnow)
