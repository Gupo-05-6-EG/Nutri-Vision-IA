from types import SimpleNamespace

import pytest
from google.genai import errors

from app.models import REASON_NOTHING_DETECTED, AnalysisStatus
from app.services import analysis_service
from app.services.food_recognition import Detection, RecognitionResult
from app.worker import tasks

RATE_LIMIT = errors.APIError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})


def _new_analysis(db) -> str:
    return analysis_service.create_analysis(db, image_mime="image/png", image_sha256="0" * 64).id


def _gemini_returns(monkeypatch, *detections):
    monkeypatch.setattr(
        tasks.food_recognition,
        "recognize_foods",
        lambda image, mime: RecognitionResult("gemini-test", list(detections)),
    )


def _gemini_raises(monkeypatch, exc):
    def _fail(image, mime):
        raise exc

    monkeypatch.setattr(tasks.food_recognition, "recognize_foods", _fail)


def _retries_left(monkeypatch, n):
    monkeypatch.setattr(tasks, "get_current_job", lambda: SimpleNamespace(retries_left=n))


def _reload(db, analysis_id):
    db.expire_all()
    return analysis_service.get_analysis(db, analysis_id)


def test_stores_items_with_taco_id(db, monkeypatch):
    analysis_id = _new_analysis(db)
    _gemini_returns(
        monkeypatch,
        Detection("Arroz, tipo 1, cozido", 3, 150.0, 0.9),
        Detection("farofa", None, 40.0, 0.8),
    )

    tasks.process_analysis(analysis_id, b"img", "image/png")

    analysis = _reload(db, analysis_id)
    assert analysis.status is AnalysisStatus.DONE
    assert analysis.model_version == "gemini-test"
    rice, farofa = analysis.items
    assert (rice.ai_taco_id, rice.taco_id, rice.ai_grams, rice.low_confidence) == (3, 3, 150.0, False)
    assert (farofa.ai_taco_id, farofa.low_confidence) == (None, True)


def test_no_food_is_not_estimated(db, monkeypatch):
    analysis_id = _new_analysis(db)
    _gemini_returns(monkeypatch)

    tasks.process_analysis(analysis_id, b"img", "image/png")

    analysis = _reload(db, analysis_id)
    assert (analysis.status, analysis.not_estimated_reason) == (
        AnalysisStatus.NOT_ESTIMATED,
        REASON_NOTHING_DETECTED,
    )


def test_rate_limit_reraises_so_rq_retries(db, monkeypatch):
    analysis_id = _new_analysis(db)
    _gemini_raises(monkeypatch, RATE_LIMIT)
    _retries_left(monkeypatch, 2)

    with pytest.raises(errors.APIError):
        tasks.process_analysis(analysis_id, b"img", "image/png")

    assert _reload(db, analysis_id).status is AnalysisStatus.PROCESSING


def test_rate_limit_on_last_attempt_marks_failed(db, monkeypatch):
    analysis_id = _new_analysis(db)
    _gemini_raises(monkeypatch, RATE_LIMIT)
    _retries_left(monkeypatch, 0)

    tasks.process_analysis(analysis_id, b"img", "image/png")

    analysis = _reload(db, analysis_id)
    assert analysis.status is AnalysisStatus.FAILED
    assert "429" in analysis.error


def test_permanent_error_fails_without_retry(db, monkeypatch):
    analysis_id = _new_analysis(db)
    _gemini_raises(monkeypatch, ValueError("broken json"))
    _retries_left(monkeypatch, 3)

    tasks.process_analysis(analysis_id, b"img", "image/png")

    assert _reload(db, analysis_id).status is AnalysisStatus.FAILED
