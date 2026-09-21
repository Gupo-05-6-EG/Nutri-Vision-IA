from collections.abc import Iterable
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    FIELD_FOOD,
    FIELD_GRAMS,
    FIELD_REMOVED,
    ORIGIN_IA,
    ORIGIN_MANUAL,
    Analysis,
    AnalysisItem,
    AnalysisStatus,
    ItemEditLog,
    utcnow,
)
from .schemas import ConfirmIn, DetectionIn, ItemPatchIn, ManualItemIn


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def _normalizar_alimento(label: Optional[str]) -> str:
    if label is None:
        return ""
    return " ".join(label.strip().casefold().split())


def _round_grams(value: float) -> float:
    return round(float(value), 2)


def _grams_iguais(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= settings.grams_epsilon


def _fmt_grams(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{float(value):.2f}"


def _recalcular_edicao(item: AnalysisItem) -> None:
    if item.origin != ORIGIN_IA:
        item.was_edited = False
        item.edited_fields = []
        return

    alterados: list[str] = []
    if item.ai_food is not None and _normalizar_alimento(
        item.food
    ) != _normalizar_alimento(item.ai_food):
        alterados.append(FIELD_FOOD)
    if item.ai_grams is not None and not _grams_iguais(item.grams, item.ai_grams):
        alterados.append(FIELD_GRAMS)

    item.edited_fields = alterados
    item.was_edited = bool(alterados)


def _log(
    db: Session,
    item: AnalysisItem,
    field: str,
    old: Optional[str],
    new: Optional[str],
    actor: Optional[str],
) -> None:
    db.add(ItemEditLog(item_id=item.id, field=field, old_value=old, new_value=new, actor=actor))


def _aplicar_correcao(
    db: Session,
    item: AnalysisItem,
    *,
    food: Optional[str],
    grams: Optional[float],
    actor: Optional[str],
) -> None:
    if food is not None and _normalizar_alimento(food) != _normalizar_alimento(item.food):
        _log(db, item, FIELD_FOOD, item.food, food, actor)
        item.food = food

    if grams is not None:
        novo = _round_grams(grams)
        if not _grams_iguais(novo, item.grams):
            _log(db, item, FIELD_GRAMS, _fmt_grams(item.grams), _fmt_grams(novo), actor)
            item.grams = novo

    _recalcular_edicao(item)
    item.updated_at = utcnow()


def _editavel(analysis: Analysis) -> None:
    if analysis.confirmed:
        raise ConflictError("analise ja confirmada nao aceita mais edicao")


def _buscar_item(analysis: Analysis, item_id: str) -> AnalysisItem:
    for item in analysis.items:
        if item.id == item_id:
            return item
    raise NotFoundError(f"item {item_id} nao encontrado na analise {analysis.id}")


def get_analysis(db: Session, analysis_id: str) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError(f"analise {analysis_id} nao encontrada")
    return analysis


def listar_edicoes(db: Session, item_id: str) -> list[ItemEditLog]:
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
    image_path: str,
    patient_id: Optional[str] = None,
    meal_type: Optional[str] = None,
) -> Analysis:
    analysis = Analysis(
        image_path=image_path,
        patient_id=patient_id,
        meal_type=meal_type,
        status=AnalysisStatus.QUEUED,
    )
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


def store_inference(
    db: Session,
    analysis_id: str,
    detections: Iterable[DetectionIn],
    *,
    model_version: str,
    inference_ms: Optional[int] = None,
) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    _editavel(analysis)

    for det in detections:
        grams = _round_grams(det.grams)
        analysis.items.append(
            AnalysisItem(
                ai_food=det.food,
                ai_grams=grams,
                ai_confidence=det.confidence,
                ai_bbox=det.bbox,
                food=det.food,
                grams=grams,
                origin=ORIGIN_IA,
                was_edited=False,
                edited_fields=[],
            )
        )

    analysis.model_version = model_version
    analysis.inference_ms = inference_ms
    analysis.status = AnalysisStatus.DONE
    analysis.error = None
    db.commit()
    return analysis


def update_item(db: Session, analysis_id: str, item_id: str, patch: ItemPatchIn) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _editavel(analysis)
    item = _buscar_item(analysis, item_id)
    if item.removed:
        raise ConflictError("item removido nao pode ser editado")

    _aplicar_correcao(db, item, food=patch.food, grams=patch.grams, actor=patch.actor)
    db.commit()
    return item


def add_manual_item(db: Session, analysis_id: str, data: ManualItemIn) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _editavel(analysis)

    item = AnalysisItem(
        food=data.food,
        grams=_round_grams(data.grams),
        origin=ORIGIN_MANUAL,
        was_edited=False,
        edited_fields=[],
    )
    analysis.items.append(item)
    db.flush()
    _log(db, item, FIELD_FOOD, None, item.food, data.actor)
    db.commit()
    return item


def remove_item(
    db: Session, analysis_id: str, item_id: str, actor: Optional[str] = None
) -> AnalysisItem:
    analysis = get_analysis(db, analysis_id)
    _editavel(analysis)
    item = _buscar_item(analysis, item_id)

    if not item.removed:
        item.removed_at = utcnow()
        _log(db, item, FIELD_REMOVED, "false", "true", actor)
        db.commit()
    return item


def confirm_analysis(db: Session, analysis_id: str, payload: ConfirmIn) -> Analysis:
    analysis = get_analysis(db, analysis_id)
    _editavel(analysis)
    if analysis.status in (AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING):
        raise ConflictError("analise ainda esta sendo processada")

    for correcao in payload.itens:
        item = _buscar_item(analysis, correcao.id)
        if item.removed:
            raise ConflictError(f"item {item.id} foi removido e nao pode ser corrigido")
        _aplicar_correcao(
            db,
            item,
            food=correcao.food,
            grams=correcao.grams,
            actor=payload.confirmed_by,
        )

    analysis.confirmed_at = utcnow()
    analysis.confirmed_by = payload.confirmed_by
    db.commit()
    return analysis
