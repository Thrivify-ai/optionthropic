import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class PositioningSignal(Base):
    __tablename__ = "positioning_signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    oi_change: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    price_change: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
