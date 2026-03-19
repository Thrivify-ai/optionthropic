"""
Buy Signal History — persisted buy signals for analytics.
Stores Buy CE / Buy PE from Quick Signals for post-trade analysis.
"""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BuySignalHistory(Base):
    __tablename__ = "buy_signal_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Optional: link to user when we have session; empty for anonymous
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)  # "Buy CE" | "Buy PE"
    level: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    momentum: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=datetime.utcnow,
    )

    __table_args__ = ()
