import uuid
from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class MaxPainLevel(Base):
    __tablename__ = "max_pain_levels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    max_pain_strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
