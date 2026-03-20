from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # QUICK | MAIN
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)  # Buy CE | Buy PE
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    outlook: Mapped[str | None] = mapped_column(String(12), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    price_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    move_2m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_3m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_5m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_10m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_30m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    outcome_2m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_3m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_5m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_10m: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_30m: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
