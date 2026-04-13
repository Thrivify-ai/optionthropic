import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BroadcastDraftStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"


class BroadcastDraft(Base):
    __tablename__ = "broadcast_drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False, default="WHATSAPP", index=True)
    post_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bias: Mapped[str | None] = mapped_column(String(20), nullable=True)
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[BroadcastDraftStatus] = mapped_column(
        SAEnum(BroadcastDraftStatus, native_enum=False),
        nullable=False,
        default=BroadcastDraftStatus.DRAFT,
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
