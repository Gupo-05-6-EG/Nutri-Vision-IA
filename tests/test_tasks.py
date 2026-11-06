from types import SimpleNamespace

import pytest
from google.genai import errors

from app.services.food_recognition import Detection, RecognitionResult
from app.worker import result_store, tasks

RATE_LIMIT = errors.APIError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
ANALYSIS_ID = "a1"


@pytest.fixture(autouse=True)
def queued_analysis():
    result_store.save({"id": ANALYSIS_ID, "status": "QUEUED"})


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


def test_stores_the_recognized_foods(monkeypatch):
    _gemini_returns(monkeypatch, Detection("Arroz, tipo 1, cozido", 3, 150.0, 0.9))

    tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    assert result_store.get(ANALYSIS_ID) == {
        "id": ANALYSIS_ID,
        "status": "DONE",
        "reason": None,
        "model_version": "gemini-test",
        "items": [{"food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 150.0, "confidence": 0.9}],
    }


def test_no_food_is_not_estimated(monkeypatch):
    _gemini_returns(monkeypatch)

    tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    analysis = result_store.get(ANALYSIS_ID)
    assert (analysis["status"], analysis["reason"]) == ("NOT_ESTIMATED", "nothing_detected")


def test_only_weak_guesses_is_low_confidence(monkeypatch):
    _gemini_returns(monkeypatch, Detection("farofa", None, 40.0, 0.9), Detection("Arroz, tipo 1, cozido", 3, 80.0, 0.2))

    tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    analysis = result_store.get(ANALYSIS_ID)
    assert (analysis["status"], analysis["reason"], len(analysis["items"])) == ("NOT_ESTIMATED", "low_confidence", 2)


def test_rate_limit_reraises_so_rq_retries(monkeypatch):
    _gemini_raises(monkeypatch, RATE_LIMIT)
    _retries_left(monkeypatch, 2)

    with pytest.raises(errors.APIError):
        tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    assert result_store.get(ANALYSIS_ID)["status"] == "PROCESSING"


def test_rate_limit_on_last_attempt_marks_failed(monkeypatch):
    _gemini_raises(monkeypatch, RATE_LIMIT)
    _retries_left(monkeypatch, 0)

    tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    analysis = result_store.get(ANALYSIS_ID)
    assert analysis["status"] == "FAILED"
    assert "429" in analysis["error"]


def test_permanent_error_fails_without_retry(monkeypatch):
    _gemini_raises(monkeypatch, ValueError("broken json"))
    _retries_left(monkeypatch, 3)

    tasks.process_analysis(ANALYSIS_ID, b"img", "image/jpeg")

    assert result_store.get(ANALYSIS_ID)["status"] == "FAILED"


def test_job_crash_marks_failed_only_after_last_retry():
    job = SimpleNamespace(id=ANALYSIS_ID, retries_left=1)

    result_store.on_job_failure(job, None, ImportError, ImportError("No module named 'httpx'"), None)
    assert result_store.get(ANALYSIS_ID)["status"] == "QUEUED"

    job.retries_left = 0
    result_store.on_job_failure(job, None, ImportError, ImportError("No module named 'httpx'"), None)
    analysis = result_store.get(ANALYSIS_ID)
    assert analysis["status"] == "FAILED"
    assert "httpx" in analysis["error"]
