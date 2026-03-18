import uuid
from datetime import date
from sqlalchemy import String, Date, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base
import enum


class OptionType(str, enum.Enum):
    CE = "CE"
    PE = "PE"


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    strike: Mapped[float] = mapped_column(nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    option_type: Mapped[OptionType] = mapped_column(SAEnum(OptionType, native_enum=False), nullable=False)
