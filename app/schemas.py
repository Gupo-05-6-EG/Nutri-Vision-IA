from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ORIGIN_MANUAL, Analysis, AnalysisItem, AnalysisStatus

GRAMS = Field(gt=0, le=100_000)
FOOD = Field(min_length=1, max_length=128)


class DetectionIn(BaseModel):

    food: str = FOOD
    grams: float = GRAMS
    confidence: float = Field(ge=0, le=1)
    bbox: Optional[dict] = None


class ItemPatchIn(BaseModel):

    food: Optional[str] = Field(default=None, min_length=1, max_length=128)
    grams: Optional[float] = Field(default=None, gt=0, le=100_000)
    actor: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _exige_algum_campo(self) -> "ItemPatchIn":
        if self.food is None and self.grams is None:
            raise ValueError("informe 'food' e/ou 'grams'")
        return self


class ManualItemIn(BaseModel):

    food: str = FOOD
    grams: float = GRAMS
    actor: Optional[str] = Field(default=None, max_length=64)


class ConfirmItemIn(BaseModel):

    id: str
    food: Optional[str] = Field(default=None, min_length=1, max_length=128)
    grams: Optional[float] = Field(default=None, gt=0, le=100_000)


class ConfirmIn(BaseModel):
    confirmed_by: Optional[str] = Field(default=None, max_length=64)
    itens: list[ConfirmItemIn] = Field(default_factory=list)


class AIEstimateOut(BaseModel):

    food: Optional[str]
    grams: Optional[float]
    confidence: Optional[float]
    bbox: Optional[dict] = None


class ConfirmadoOut(BaseModel):

    food: str
    grams: float


class ItemOut(BaseModel):
    id: str
    ai: Optional[AIEstimateOut]
    confirmado: ConfirmadoOut
    was_edited: bool
    edited_fields: list[str]
    grams_delta: Optional[float]
    origin: str
    removido: bool

    @classmethod
    def from_model(cls, item: AnalysisItem) -> "ItemOut":
        ai = None
        if item.origin != ORIGIN_MANUAL:
            ai = AIEstimateOut(
                food=item.ai_food,
                grams=None if item.ai_grams is None else float(item.ai_grams),
                confidence=item.ai_confidence,
                bbox=item.ai_bbox,
            )
        return cls(
            id=item.id,
            ai=ai,
            confirmado=ConfirmadoOut(food=item.food, grams=float(item.grams)),
            was_edited=item.was_edited,
            edited_fields=list(item.edited_fields or []),
            grams_delta=item.grams_delta,
            origin=item.origin,
            removido=item.removed,
        )


class AnalysisCreatedOut(BaseModel):
    id: str
    status: AnalysisStatus


class AnalysisOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    status: AnalysisStatus
    error: Optional[str] = None
    model_version: Optional[str] = None
    inference_ms: Optional[int] = None
    meal_type: Optional[str] = None
    confirmado: bool
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    itens: list[ItemOut]

    @classmethod
    def from_model(cls, analysis: Analysis) -> "AnalysisOut":
        return cls(
            id=analysis.id,
            status=analysis.status,
            error=analysis.error,
            model_version=analysis.model_version,
            inference_ms=analysis.inference_ms,
            meal_type=analysis.meal_type,
            confirmado=analysis.confirmed,
            confirmed_at=analysis.confirmed_at,
            created_at=analysis.created_at,
            itens=[ItemOut.from_model(i) for i in analysis.items],
        )
