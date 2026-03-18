import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class GammaLevel(Base):
    __tablename__ = "gamma_levels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    support_strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    resistance_strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    call_wall: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    put_wall: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
