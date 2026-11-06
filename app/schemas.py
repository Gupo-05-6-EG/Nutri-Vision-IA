from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.services.analysis_result import AnalysisStatus


class ItemOut(BaseModel):
    food: str
    taco_id: Optional[int] = None
    grams: float
    confidence: float


class AnalysisCreatedOut(BaseModel):
    id: str
    status: AnalysisStatus
    reason: Optional[str] = None
    issues: Optional[list[str]] = None


class AnalysisOut(AnalysisCreatedOut):
    model_config = ConfigDict(protected_namespaces=())

    error: Optional[str] = None
    model_version: Optional[str] = None
    items: Optional[list[ItemOut]] = None
