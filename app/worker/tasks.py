from typing import Optional

from rq import get_current_job

from app.services import analysis_result, food_recognition
from app.services.analysis_result import AnalysisStatus
from app.worker import result_store


def _is_last_attempt() -> bool:
    job = get_current_job()
    return job is None or not job.retries_left


def process_analysis(analysis_id: str, image: bytes, mime_type: str, plate_type: Optional[str] = None) -> None:
    result_store.update(analysis_id, status=AnalysisStatus.PROCESSING.value)

    try:
        recognition = food_recognition.recognize_foods(image, mime_type, plate_type=plate_type)
    except Exception as exc:
        if food_recognition.is_transient_error(exc) and not _is_last_attempt():
            raise
        result_store.update(
            analysis_id,
            status=AnalysisStatus.FAILED.value,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    result_store.save(
        {
            "id": analysis_id,
            "model_version": recognition.model_version,
            **analysis_result.build_result(recognition.detections),
        }
    )
