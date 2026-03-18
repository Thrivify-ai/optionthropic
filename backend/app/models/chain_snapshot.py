import uuid
from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class ChainSnapshot(Base):
    __tablename__ = "chain_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    call_oi: Mapped[int] = mapped_column(nullable=False, default=0)
    put_oi: Mapped[int] = mapped_column(nullable=False, default=0)
    call_volume: Mapped[int] = mapped_column(nullable=False, default=0)
    put_volume: Mapped[int] = mapped_column(nullable=False, default=0)
    underlying_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
