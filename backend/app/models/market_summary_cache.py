from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class MarketSummaryCache(Base):
    __tablename__ = "market_summary_cache"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    insight: Mapped[str] = mapped_column(String(4000), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
