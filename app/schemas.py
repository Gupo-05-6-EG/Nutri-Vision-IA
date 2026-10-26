from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ORIGIN_MANUAL, Analysis, AnalysisItem, AnalysisStatus

GRAMS = Field(gt=0, le=100_000)
OPTIONAL_GRAMS = Field(default=None, gt=0, le=100_000)
OPTIONAL_FOOD = Field(default=None, min_length=1, max_length=128)
ACTOR = Field(default=None, max_length=64)


class DetectionIn(BaseModel):

    food: str = Field(min_length=1, max_length=128)
    taco_id: Optional[int] = None
    grams: float = GRAMS
    confidence: float = Field(ge=0, le=1)


class ItemPatchIn(BaseModel):

    food: Optional[str] = OPTIONAL_FOOD
    taco_id: Optional[int] = None
    grams: Optional[float] = OPTIONAL_GRAMS
    actor: Optional[str] = ACTOR

    @model_validator(mode="after")
    def _require_some_field(self) -> "ItemPatchIn":
        if self.food is None and self.taco_id is None and self.grams is None:
            raise ValueError("provide 'taco_id', 'food' and/or 'grams'")
        return self


class ManualItemIn(BaseModel):

    food: Optional[str] = OPTIONAL_FOOD
    taco_id: Optional[int] = None
    grams: float = GRAMS
    actor: Optional[str] = ACTOR

    @model_validator(mode="after")
    def _require_food(self) -> "ManualItemIn":
        if self.food is None and self.taco_id is None:
            raise ValueError("provide 'taco_id' or 'food'")
        return self


class ConfirmItemIn(BaseModel):

    id: str
    food: Optional[str] = OPTIONAL_FOOD
    taco_id: Optional[int] = None
    grams: Optional[float] = OPTIONAL_GRAMS


class ConfirmIn(BaseModel):
    confirmed_by: Optional[str] = ACTOR
    items: list[ConfirmItemIn] = Field(default_factory=list)


class AIEstimateOut(BaseModel):

    food: Optional[str]
    taco_id: Optional[int]
    grams: Optional[float]
    confidence: Optional[float]


class QualityOut(BaseModel):
    sharpness: float
    brightness: float
    issues: list[str]
    ok: bool


class ConfirmedOut(BaseModel):

    food: str
    taco_id: Optional[int]
    grams: float


class ItemOut(BaseModel):
    id: str
    ai: Optional[AIEstimateOut]
    confirmed: ConfirmedOut
    was_edited: bool
    edited_fields: list[str]
    grams_delta: Optional[float]
    origin: str
    low_confidence: bool
    removed: bool

    @classmethod
    def from_model(cls, item: AnalysisItem) -> "ItemOut":
        ai = None
        if item.origin != ORIGIN_MANUAL:
            ai = AIEstimateOut(
                food=item.ai_food,
                taco_id=item.ai_taco_id,
                grams=None if item.ai_grams is None else float(item.ai_grams),
                confidence=item.ai_confidence,
            )
        return cls(
            id=item.id,
            ai=ai,
            confirmed=ConfirmedOut(food=item.food, taco_id=item.taco_id, grams=float(item.grams)),
            was_edited=item.was_edited,
            edited_fields=list(item.edited_fields or []),
            grams_delta=item.grams_delta,
            origin=item.origin,
            low_confidence=item.low_confidence,
            removed=item.removed,
        )


class FoodOut(BaseModel):
    id: int
    name: str
    category: str


class AnalysisCreatedOut(BaseModel):
    id: str
    status: AnalysisStatus
    reason: Optional[str] = None
    quality: Optional[QualityOut] = None


class AnalysisOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    status: AnalysisStatus
    reason: Optional[str] = None
    quality: Optional[QualityOut] = None
    error: Optional[str] = None
    model_version: Optional[str] = None
    inference_ms: Optional[int] = None
    meal_type: Optional[str] = None
    confirmed: bool
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    items: list[ItemOut]

    @classmethod
    def from_model(cls, analysis: Analysis) -> "AnalysisOut":
        return cls(
            id=analysis.id,
            status=analysis.status,
            reason=analysis.not_estimated_reason,
            quality=None if analysis.quality is None else QualityOut(**analysis.quality),
            error=analysis.error,
            model_version=analysis.model_version,
            inference_ms=analysis.inference_ms,
            meal_type=analysis.meal_type,
            confirmed=analysis.confirmed,
            confirmed_at=analysis.confirmed_at,
            created_at=analysis.created_at,
            items=[ItemOut.from_model(i) for i in analysis.items],
        )
