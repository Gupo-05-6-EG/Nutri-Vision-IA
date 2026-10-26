import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas import (
    AnalysisCreatedOut,
    AnalysisOut,
    ConfirmIn,
    ItemOut,
    ItemPatchIn,
    ManualItemIn,
    QualityOut,
)
from app.services import analysis_service, image_compression, image_quality
from app.worker import job_queue

router = APIRouter(prefix="/analyses", tags=["analyses"])


def _read_upload(file: UploadFile) -> bytes:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="send an image file",
        )

    content = file.file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"image larger than {settings.max_upload_bytes} bytes",
        )
    return content


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalysisCreatedOut,
    summary="Upload a meal photo to the analysis queue",
)
def create_analysis(
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(default=None),
    meal_type: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
) -> AnalysisCreatedOut:
    try:
        image = image_compression.compress_image(_read_upload(file))
    except image_compression.InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))

    quality = image_quality.assess_image(image)

    analysis = analysis_service.create_analysis(
        db,
        image_mime=image_compression.COMPRESSED_MIME_TYPE,
        image_sha256=hashlib.sha256(image).hexdigest(),
        patient_id=patient_id,
        meal_type=meal_type,
        quality=quality,
    )

    if quality.ok:
        try:
            job_queue.enqueue_analysis(analysis.id, image, image_compression.COMPRESSED_MIME_TYPE)
        except RedisError as exc:
            analysis_service.mark_failed(db, analysis.id, f"queue unavailable: {exc}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="analysis queue unavailable, try again",
            )

    return AnalysisCreatedOut(
        id=analysis.id,
        status=analysis.status,
        reason=analysis.not_estimated_reason,
        quality=QualityOut(**quality.as_dict()),
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisOut,
    summary="Analysis result: AI estimate side by side with the confirmed values",
)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisOut:
    return AnalysisOut.from_model(analysis_service.get_analysis(db, analysis_id))


@router.patch(
    "/{analysis_id}/items/{item_id}",
    response_model=ItemOut,
    summary="Correct the food and/or grams of an item",
)
def update_item(
    analysis_id: str,
    item_id: str,
    patch: ItemPatchIn,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(analysis_service.update_item(db, analysis_id, item_id, patch))


@router.post(
    "/{analysis_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=ItemOut,
    summary="Add a food the AI did not detect",
)
def add_item(
    analysis_id: str,
    data: ManualItemIn,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(analysis_service.add_manual_item(db, analysis_id, data))


@router.delete(
    "/{analysis_id}/items/{item_id}",
    response_model=ItemOut,
    summary="Remove an item from the meal (soft delete, keeps the AI estimate)",
)
def remove_item(
    analysis_id: str,
    item_id: str,
    actor: Optional[str] = None,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(analysis_service.remove_item(db, analysis_id, item_id, actor))


@router.post(
    "/{analysis_id}/confirm",
    response_model=AnalysisOut,
    summary="Close the meal, accepting batch corrections",
)
def confirm_analysis(
    analysis_id: str,
    payload: Optional[ConfirmIn] = None,
    db: Session = Depends(get_db),
) -> AnalysisOut:
    return AnalysisOut.from_model(
        analysis_service.confirm_analysis(db, analysis_id, payload or ConfirmIn())
    )
