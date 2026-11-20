from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from rq import Queue

from app.main import app
from app.services.food_recognition import Detection, RecognitionResult
from app.worker import job_queue, tasks


@pytest.fixture
def gemini_calls(monkeypatch):
    calls = []

    def _recognize(image, mime, plate_type=None):
        calls.append((image, mime, plate_type))
        return RecognitionResult(
            "gemini-test",
            [
                Detection("Arroz, tipo 1, cozido", 3, 150.0, 0.9),
                Detection("farofa", None, 40.0, 0.8),
            ],
        )

    monkeypatch.setattr(tasks.food_recognition, "recognize_foods", _recognize)
    return calls


@pytest.fixture
def client(gemini_calls):
    with TestClient(app) as c:
        yield c


def _upload(client, photo, mime="image/png"):
    return client.post("/api/v1/analyses", files={"file": ("meal.png", photo, mime)})


def test_upload_returns_id_and_result_has_only_the_analysis(client, sharp_photo):
    created = _upload(client, sharp_photo)
    assert created.status_code == 202, created.text
    assert set(created.json()) == {"id", "status"}

    analysis = client.get(f"/api/v1/analyses/{created.json()['id']}").json()

    assert analysis == {
        "id": created.json()["id"],
        "status": "DONE",
        "model_version": "gemini-test",
        "items": [
            {"food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 150.0, "confidence": 0.9},
            {"food": "farofa", "grams": 40.0, "confidence": 0.8},
        ],
    }


def test_bad_photo_is_answered_right_away_and_not_queued(client, fake_redis, gemini_calls, blurry_photo):
    created = _upload(client, blurry_photo).json()

    assert (created["status"], created["reason"], created["issues"]) == ("NOT_ESTIMATED", "bad_photo", ["blurry"])
    assert client.get(f"/api/v1/analyses/{created['id']}").json()["items"] == []
    assert gemini_calls == []
    assert Queue(job_queue.QUEUE_NAME, connection=fake_redis).count == 0


def test_result_expires(client, fake_redis, sharp_photo):
    analysis_id = _upload(client, sharp_photo).json()["id"]

    ttl = fake_redis.ttl(f"nutrivision:analysis:{analysis_id}")

    assert 0 < ttl <= 24 * 3600


def test_upload_is_compressed_before_queueing(client, gemini_calls, sharp_photo):
    large = BytesIO()
    Image.open(BytesIO(sharp_photo)).resize((3000, 2000)).save(large, "PNG")

    assert _upload(client, large.getvalue()).status_code == 202

    [(image, mime, _plate)] = gemini_calls
    sent = Image.open(BytesIO(image))
    assert (mime, sent.format, max(sent.size)) == ("image/jpeg", "JPEG", 1280)
    assert len(image) < len(large.getvalue())


def test_unknown_analysis_returns_404(client):
    assert client.get("/api/v1/analyses/does-not-exist").status_code == 404


def test_file_that_is_not_an_image(client):
    assert _upload(client, b"not a photo", mime="image/jpeg").status_code == 415


def test_non_image_content_type(client, sharp_photo):
    assert _upload(client, sharp_photo, mime="application/pdf").status_code == 415


def test_removed_routes_are_gone(client):
    paths = set(client.get("/openapi.json").json()["paths"])

    assert paths == {"/api/v1/analyses", "/api/v1/analyses/{analysis_id}", "/health"}


def test_health_with_redis(client):
    assert client.get("/health").json() == {"status": "ok", "redis": "ok"}


def test_plate_type_reaches_the_recognition(client, gemini_calls, sharp_photo):
    created = client.post(
        "/api/v1/analyses",
        files={"file": ("meal.png", sharp_photo, "image/png")},
        data={"plate_type": "deep"},
    )

    assert created.status_code == 202, created.text
    assert gemini_calls[-1][2] == "deep"


def test_invalid_plate_type_is_rejected(client, gemini_calls, sharp_photo):
    created = client.post(
        "/api/v1/analyses",
        files={"file": ("meal.png", sharp_photo, "image/png")},
        data={"plate_type": "tray"},
    )

    assert created.status_code == 422
    assert gemini_calls == []
