from collections.abc import Iterable
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    FIELD_FOOD,
    FIELD_GRAMS,
    FIELD_REMOVED,
    ORIGIN_AI,
    ORIGIN_MANUAL,
    REASON_BAD_PHOTO,
    REASON_LOW_CONFIDENCE,
    REASON_NOTHING_DETECTED,
    Analysis,
    AnalysisItem,
    AnalysisStatus,
    ItemEditLog,
    utcnow,
)
from app.schemas import ConfirmIn, DetectionIn, ItemPatchIn, ManualItemIn
from app.services import taco_table
from app.services.image_quality import ImageQuality


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class InvalidInputError(Exception):
    pass


def _normalize_food_name(label: Optional[str]) -> str:
    if label is None:
        return ""
    return " ".join(label.strip().casefold().split())


def _resolve_food(food: Optional[str], taco_id: Optional[int]) -> tuple:
    if taco_id is None:
        return food, None
    taco_food = taco_table.get_food(taco_id)
    if taco_food is None:
        raise InvalidInputError(f"taco_id {taco_id} does not exist in the TACO table")
    return taco_food.name, taco_food.id


def _round_grams(value: float) -> float:
    return round(float(value), 2)


def _grams_equal(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= settings.grams_epsilon


def _format_grams(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{float(value):.2f}"


def _refresh_edit_state(item: AnalysisItem) -> None:
    if item.origin != ORIGIN_AI:
        item.was_edited = False
        item.edited_fields = []
        return

    changed: list[str] = []
    if item.ai_food is not None and (
        item.taco_id != item.ai_taco_id
        or _normalize_food_name(item.food) != _normalize_food_name(item.ai_food)
    ):
        changed.append(FIELD_FOOD)
    if item.ai_grams is not None and not _grams_equal(item.grams, item.ai_grams):
        changed.append(FIELD_GRAMS)

    item.edited_fields = changed
    item.was_edited = bool(changed)


def _log_edit(
    db: Session,
    item: AnalysisItem,
    field: str,
    old: Optional[str],
    new: Optional[str],
    actor: Optional[str],
) -> None:
    db.add(ItemEditLog(item_id=item.id, field=field, old_value=old, new_value=new, actor=actor))


def _apply_correction(
    db: Session,
    item: AnalysisItem,
    *,
    food: Optional[str],
    taco_id: Optional[int],
    grams: Optional[float],
    actor: Optional[str],
) -> None:
    if food is not None or taco_id is not None:
        food, taco_id = _resolve_food(food, taco_id)
        if taco_id != item.taco_id or _normalize_food_name(food) != _normalize_food_name(item.food):
            _log_edit(db, item, FIELD_FOOD, item.food, food, actor)
            item.food = food
            item.taco_id = taco_id

    if grams is not None:
        new_grams = _round_grams(grams)
        if not _grams_equal(new_grams, item.grams):
            _log_edit(db, item, FIELD_GRAMS, _format_grams(item.grams), _format_grams(new_grams), actor)
            item.grams = new_grams

    _refresh_edit_state(item)
    item.updated_at = utcnow()


def _ensure_editable(analysis: Analysis) -> None:
    if analysis.confirmed:
        raise ConflictError("analysis is already confirmed and can no longer be edited")


def _find_item(analysis: Analysis, item_id: str) -> AnalysisItem:
    for item in analysis.items:
        if item.id == item_id:
            return item
    raise NotFoundError(f"item {item_id} not found in analysis {analysis.id}")


def get_analysis(db: Session, analysis_id: str) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError(f"analysis {analysis_id} not found")
    return analysis


def list_item_edits(db: Session, item_id: str) -> list[ItemEditLog]:
    return list(
        db.scalars(
            select(ItemEditLog)
            .where(ItemEditLog.item_id == item_id)
            .order_by(ItemEditLog.created_at)
        )
    )


def create_analysis(
    db: Session,
    *,
    image_mime: str,
    image_sha256: str,
    patient_id: Optional[str] = None,
    meal_type: Optional[str] = None,
    quality: Optional[ImageQuality] = None,
) -> Analysis:
    analysis = Analysis(
        image_mime=image_mime,
        image_sha256=image_sha256,
        patient_id=patient_id,
        meal_type=meal_type,
        status=AnalysisStatus.QUEUED,
    )
    if quality is not None:
        analysis.quality = quality.as_dict()
        if not quality.ok:
            analysis.status = AnalysisStatus.NOT_ESTIMATED
            analysis.not_estimated_reason = REASON_BAD_PHOTO
    db.add(analysis)
    db.commit()
    return analysis


def mark_processing(db: Session, analysis_id: str) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    analysis.status = AnalysisStatus.PROCESSING
    db.commit()
    return analysis


def mark_failed(db: Session, analysis_id: str, error: str) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    analysis.status = AnalysisStatus.FAILED
    analysis.error = error[:2000]
    db.commit()
    return analysis


def store_recognition(
    db: Session,
    analysis_id: str,
    detections: Iterable[DetectionIn],
    *,
    model_version: str,
    inference_ms: Optional[int] = None,
) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    _ensure_editable(analysis)

    detections = list(detections)
    reliable = 0
    for det in detections:
        grams = _round_grams(det.grams)
        weak = det.confidence < settings.min_confidence or det.taco_id is None
        reliable += 0 if weak else 1
        analysis.items.append(
            AnalysisItem(
                ai_food=det.food,
                ai_taco_id=det.taco_id,
                ai_grams=grams,
                ai_confidence=det.confidence,
                food=det.food,
                taco_id=det.taco_id,
                grams=grams,
                low_confidence=weak,
                origin=ORIGIN_AI,
                was_edited=False,
                edited_fields=[],
            )
        )

    analysis.model_version = model_version
    analysis.inference_ms = inference_ms
    analysis.error = None

    if not detections:
        analysis.status = AnalysisStatus.NOT_ESTIMATED
        analysis.not_estimated_reason = REASON_NOTHING_DETECTED
    elif reliable == 0:
        analysis.status = AnalysisStatus.NOT_ESTIMATED
        analysis.not_estimated_reason = REASON_LOW_CONFIDENCE
    else:
        analysis.status = AnalysisStatus.DONE
        analysis.not_estimated_reason = None

    db.commit()
    return analysis


def update_item(db: Session, analysis_id: str, item_id: str, patch: ItemPatchIn) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _ensure_editable(analysis)
    item = _find_item(analysis, item_id)
    if item.removed:
        raise ConflictError("removed item cannot be edited")

    _apply_correction(
        db, item, food=patch.food, taco_id=patch.taco_id, grams=patch.grams, actor=patch.actor
    )
    db.commit()
    return item


def add_manual_item(db: Session, analysis_id: str, data: ManualItemIn) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _ensure_editable(analysis)
    food, taco_id = _resolve_food(data.food, data.taco_id)

    item = AnalysisItem(
        food=food,
        taco_id=taco_id,
        grams=_round_grams(data.grams),
        origin=ORIGIN_MANUAL,
        was_edited=False,
        edited_fields=[],
    )
    analysis.items.append(item)
    db.flush()
    _log_edit(db, item, FIELD_FOOD, None, item.food, data.actor)
    db.commit()
    return item


def remove_item(
    db: Session, analysis_id: str, item_id: str, actor: Optional[str] = None
) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _ensure_editable(analysis)
    item = _find_item(analysis, item_id)

    if not item.removed:
        item.removed_at = utcnow()
        _log_edit(db, item, FIELD_REMOVED, "false", "true", actor)
        db.commit()
    return item


def confirm_analysis(db: Session, analysis_id: str, payload: ConfirmIn) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    _ensure_editable(analysis)
    if analysis.status in (AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING):
        raise ConflictError("analysis is still being processed")

    for correction in payload.items:
        item = _find_item(analysis, correction.id)
        if item.removed:
            raise ConflictError(f"item {item.id} was removed and cannot be corrected")
        _apply_correction(
            db,
            item,
            food=correction.food,
            taco_id=correction.taco_id,
            grams=correction.grams,
            actor=payload.confirmed_by,
        )

    analysis.confirmed_at = utcnow()
    analysis.confirmed_by = payload.confirmed_by
    db.commit()
    return analysis
