import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Numeric, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base
import enum


class FlowSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class FlowType(str, enum.Enum):
    SWEEP = "SWEEP"
    BLOCK = "BLOCK"
    UNUSUAL = "UNUSUAL"
    NORMAL = "NORMAL"


class OptionsFlow(Base):
    __tablename__ = "options_flow"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    side: Mapped[FlowSide] = mapped_column(SAEnum(FlowSide, native_enum=False), nullable=False)
    volume: Mapped[int] = mapped_column(nullable=False)
    premium: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    flow_type: Mapped[FlowType] = mapped_column(SAEnum(FlowType, native_enum=False), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
