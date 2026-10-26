import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue

from app.main import app
from app.services import analysis_service
from app.services.food_recognition import Detection, RecognitionResult
from app.worker import job_queue, tasks


@pytest.fixture
def fake_redis(monkeypatch):
    connection = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(job_queue, "get_redis", lambda: connection)
    monkeypatch.setattr(
        job_queue,
        "get_queue",
        lambda: Queue(job_queue.QUEUE_NAME, connection=connection, is_async=False),
    )
    return connection


@pytest.fixture
def client(fake_redis, monkeypatch):
    monkeypatch.setattr(
        tasks.food_recognition,
        "recognize_foods",
        lambda image, mime: RecognitionResult(
            "gemini-test",
            [
                Detection("Arroz, tipo 1, cozido", 3, 150.0, 0.9),
                Detection("Frango, filé, grelhado", 409, 120.0, 0.85),
            ],
        ),
    )
    with TestClient(app) as c:
        yield c


def _upload(client, photo, mime="image/png"):
    return client.post("/api/v1/analyses", files={"file": ("meal.png", photo, mime)})


def test_full_flow_with_correction_by_taco_id(client, db, sharp_photo):
    created = _upload(client, sharp_photo)
    assert created.status_code == 202, created.text
    analysis_id = created.json()["id"]

    analysis = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert analysis["status"] == "DONE"
    rice, chicken = analysis["items"]
    assert rice["ai"]["taco_id"] == 3

    corrected = client.patch(
        f"/api/v1/analyses/{analysis_id}/items/{rice['id']}",
        json={"taco_id": 561, "grams": 100, "actor": "patient"},
    ).json()
    assert corrected["confirmed"] == {"food": "Feijão, carioca, cozido", "taco_id": 561, "grams": 100.0}
    assert corrected["ai"] == {"food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 150.0, "confidence": 0.9}
    assert corrected["edited_fields"] == ["food", "grams"]
    assert {e.field for e in analysis_service.list_item_edits(db, rice["id"])} == {"food", "grams"}

    confirmed = client.post(f"/api/v1/analyses/{analysis_id}/confirm", json={}).json()
    assert confirmed["confirmed"] is True


def test_unknown_taco_id_returns_422(client, sharp_photo):
    analysis_id = _upload(client, sharp_photo).json()["id"]
    item_id = client.get(f"/api/v1/analyses/{analysis_id}").json()["items"][0]["id"]

    response = client.patch(f"/api/v1/analyses/{analysis_id}/items/{item_id}", json={"taco_id": 9999})

    assert response.status_code == 422


def test_manual_item_from_taco(client, sharp_photo):
    analysis_id = _upload(client, sharp_photo).json()["id"]

    item = client.post(f"/api/v1/analyses/{analysis_id}/items", json={"taco_id": 10, "grams": 80}).json()

    assert item["confirmed"] == {"food": "Brócolis, cozido", "taco_id": 10, "grams": 80.0}
    assert item["origin"] == "manual"


def test_bad_photo_is_not_queued(client, fake_redis, blurry_photo):
    response = _upload(client, blurry_photo).json()

    assert (response["status"], response["reason"]) == ("NOT_ESTIMATED", "bad_photo")
    assert response["quality"]["issues"] == ["blurry"]
    assert Queue(job_queue.QUEUE_NAME, connection=fake_redis).count == 0


def test_unsupported_format(client, sharp_photo):
    assert _upload(client, sharp_photo, mime="image/gif").status_code == 415


def test_food_search(client):
    response = client.get("/api/v1/foods", params={"search": "frango"})

    assert response.json() == [{"id": 409, "name": "Frango, filé, grelhado", "category": "Carnes e derivados"}]


def test_health_with_redis(client):
    assert client.get("/health").json() == {"status": "ok", "redis": "ok"}
