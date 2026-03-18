import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class CommoditySnapshot(Base):
    __tablename__ = "commodity_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # e.g. CRUDEOIL, NATGAS, GOLD, SILVER
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    oi: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

