import time

from rq import get_current_job

from app.core.database import SessionLocal
from app.schemas import DetectionIn
from app.services import analysis_service, food_recognition


def _is_last_attempt() -> bool:
    job = get_current_job()
    return job is None or not job.retries_left


def process_analysis(analysis_id: str, image: bytes, mime_type: str) -> None:
    started = time.perf_counter()

    with SessionLocal() as db:
        try:
            analysis_service.mark_processing(db, analysis_id)
        except analysis_service.NotFoundError:
            return

        try:
            result = food_recognition.recognize_foods(image, mime_type)
            detections = [
                DetectionIn(food=d.food, taco_id=d.taco_id, grams=d.grams, confidence=d.confidence)
                for d in result.detections
            ]
            analysis_service.store_recognition(
                db,
                analysis_id,
                detections,
                model_version=result.model_version,
                inference_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            db.rollback()
            if food_recognition.is_transient_error(exc) and not _is_last_attempt():
                raise
            analysis_service.mark_failed(db, analysis_id, f"{type(exc).__name__}: {exc}")
