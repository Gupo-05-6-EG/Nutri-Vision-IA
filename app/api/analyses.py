import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas import AnalysisCreatedOut, AnalysisOut
from app.services import image_compression, image_quality
from app.services.analysis_result import REASON_BAD_PHOTO, AnalysisStatus
from app.worker import job_queue, result_store

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
    response_model_exclude_none=True,
    summary="Upload a meal photo to the analysis queue",
)
def create_analysis(file: UploadFile = File(...)) -> AnalysisCreatedOut:
    try:
        image = image_compression.compress_image(_read_upload(file))
    except image_compression.InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))

    quality = image_quality.assess_image(image)
    analysis_id = str(uuid.uuid4())

    if not quality.ok:
        analysis = {
            "id": analysis_id,
            "status": AnalysisStatus.NOT_ESTIMATED.value,
            "reason": REASON_BAD_PHOTO,
            "issues": list(quality.issues),
            "items": [],
        }
        result_store.save(analysis)
        return AnalysisCreatedOut(**analysis)

    result_store.save({"id": analysis_id, "status": AnalysisStatus.QUEUED.value})
    try:
        job_queue.enqueue_analysis(analysis_id, image, image_compression.COMPRESSED_MIME_TYPE)
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis queue unavailable, try again",
        )
    return AnalysisCreatedOut(id=analysis_id, status=AnalysisStatus.QUEUED)


@router.get(
    "/{analysis_id}",
    response_model=AnalysisOut,
    response_model_exclude_none=True,
    summary="Analysis result: foods identified in the photo",
)
def get_analysis(analysis_id: str) -> AnalysisOut:
    analysis = result_store.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis not found")
    return AnalysisOut(**analysis)
