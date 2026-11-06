import enum
from collections.abc import Iterable

from app.core.config import settings

REASON_BAD_PHOTO = "bad_photo"
REASON_NOTHING_DETECTED = "nothing_detected"
REASON_LOW_CONFIDENCE = "low_confidence"


class AnalysisStatus(str, enum.Enum):

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"
    NOT_ESTIMATED = "NOT_ESTIMATED"


def _is_reliable(detection) -> bool:
    return detection.taco_id is not None and detection.confidence >= settings.min_confidence


def build_result(detections: Iterable) -> dict:
    detections = list(detections)
    items = [
        {
            "food": d.food,
            "taco_id": d.taco_id,
            "grams": round(float(d.grams), 2),
            "confidence": d.confidence,
        }
        for d in detections
    ]

    if not detections:
        status, reason = AnalysisStatus.NOT_ESTIMATED, REASON_NOTHING_DETECTED
    elif not any(_is_reliable(d) for d in detections):
        status, reason = AnalysisStatus.NOT_ESTIMATED, REASON_LOW_CONFIDENCE
    else:
        status, reason = AnalysisStatus.DONE, None

    return {"status": status.value, "reason": reason, "items": items}
