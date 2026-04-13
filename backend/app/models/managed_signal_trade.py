from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ManagedSignalTrade(Base):
    __tablename__ = "managed_signal_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    entry_signal: Mapped[str] = mapped_column(String(20), nullable=False)
    latest_signal: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_version: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    entry_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entry_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    latest_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    latest_points: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    success_threshold_points: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    stop_points: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    hold_cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_favorable_points: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    max_adverse_points: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    entry_reason: Mapped[str | None] = mapped_column(String(768), nullable=True)
    latest_reason: Mapped[str | None] = mapped_column(String(768), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(768), nullable=True)
    result_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_signal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    realized_points: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
