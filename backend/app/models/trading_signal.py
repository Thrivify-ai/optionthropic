from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TradingSignalRow(Base):
    __tablename__ = "trading_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)  # "Buy CE" | "Buy PE" | "Wait"
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)

    support: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    resistance: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    bias_5m: Mapped[str] = mapped_column(String(10), nullable=False)
    bias_30m: Mapped[str] = mapped_column(String(10), nullable=False)
    bias_60m: Mapped[str] = mapped_column(String(10), nullable=False)

    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=datetime.utcnow,
    )

