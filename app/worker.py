import time

from . import service
from .db import SessionLocal
from .schemas import DetectionIn
from .vision import Detector


def processar_analise(analysis_id: str, detector: Detector) -> None:
    inicio = time.perf_counter()

    with SessionLocal() as db:
        try:
            analysis = service.mark_processing(db, analysis_id)
        except service.NotFoundError:
            return

        try:
            resultado = detector.detectar(analysis.image_path)
            deteccoes = [
                DetectionIn(food=d.food, grams=d.grams, confidence=d.confidence, bbox=d.bbox)
                for d in resultado.detections
            ]
            service.store_inference(
                db,
                analysis_id,
                deteccoes,
                model_version=resultado.model_version,
                inference_ms=int((time.perf_counter() - inicio) * 1000),
            )
        except Exception as exc:
            db.rollback()
            service.mark_failed(db, analysis_id, f"{type(exc).__name__}: {exc}")
