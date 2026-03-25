import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class GlobalNewsAlert(Base):
    __tablename__ = "global_news_alerts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="rss")
    source: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )
    impact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    move_potential: Mapped[str] = mapped_column(String(20), nullable=False, default="WATCH")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    affected_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    matched_themes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    impact_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
