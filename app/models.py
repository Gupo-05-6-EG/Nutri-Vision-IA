import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ORIGIN_IA = "ia"
ORIGIN_MANUAL = "manual"

FIELD_FOOD = "food"
FIELD_GRAMS = "grams"
FIELD_REMOVED = "removed"


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisStatus(str, enum.Enum):

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Analysis(Base):

    __tablename__ = "analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, default=None)
    image_path: Mapped[str] = mapped_column(String(512))

    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, native_enum=False, length=16),
        default=AnalysisStatus.QUEUED,
        index=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)

    model_version: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    inference_ms: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    meal_type: Mapped[Optional[str]] = mapped_column(String(32), default=None)

    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    items: Mapped[list["AnalysisItem"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysisItem.created_at",
    )

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None


class AnalysisItem(Base):

    __tablename__ = "analysis_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), index=True
    )

    ai_food: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    ai_grams: Mapped[Optional[float]] = mapped_column(Numeric(8, 2, asdecimal=False), default=None)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    ai_bbox: Mapped[Optional[dict]] = mapped_column(JSON, default=None)

    food: Mapped[str] = mapped_column(String(128))
    grams: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False))

    origin: Mapped[str] = mapped_column(String(8), default=ORIGIN_IA, index=True)
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    edited_fields: Mapped[list] = mapped_column(JSON, default=list)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    analysis: Mapped[Analysis] = relationship(back_populates="items")
    edits: Mapped[list["ItemEditLog"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemEditLog.created_at",
    )

    @property
    def removed(self) -> bool:
        return self.removed_at is not None

    @property
    def grams_delta(self) -> Optional[float]:
        if self.ai_grams is None:
            return None
        return round(float(self.grams) - float(self.ai_grams), 2)


class ItemEditLog(Base):

    __tablename__ = "item_edit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_item.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(16))
    old_value: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    new_value: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    actor: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[AnalysisItem] = relationship(back_populates="edits")
