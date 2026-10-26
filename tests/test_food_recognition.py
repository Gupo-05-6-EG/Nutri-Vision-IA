import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.services import food_recognition, taco_table


class _FakeClient:
    def __init__(self, response: dict):
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._text = json.dumps(response)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self._text)


@pytest.fixture
def gemini(monkeypatch):
    def _install(response: dict) -> _FakeClient:
        fake = _FakeClient(response)
        monkeypatch.setattr(food_recognition, "_client", lambda: fake)
        return fake

    return _install


def test_maps_items_to_taco(gemini):
    fake = gemini(
        {
            "is_food": True,
            "items": [
                {"taco_id": 3, "name": "rice", "grams": 150, "confidence": 0.9},
                {"taco_id": 409, "name": "chicken", "grams": 120.5, "confidence": 0.8},
            ],
        }
    )

    result = food_recognition.recognize_foods(b"img", "image/jpeg")

    assert [(d.food, d.taco_id, d.grams) for d in result.detections] == [
        ("Arroz, tipo 1, cozido", 3, 150),
        ("Frango, filé, grelhado", 409, 120.5),
    ]
    prompt = fake.calls[0]["contents"][1]
    assert "561|Feijão, carioca, cozido" in prompt


def test_unknown_taco_id_keeps_gemini_name(gemini):
    gemini({"is_food": True, "items": [{"taco_id": 9999, "name": "farofa", "grams": 40, "confidence": 0.7}]})

    [det] = food_recognition.recognize_foods(b"img", "image/jpeg").detections

    assert (det.food, det.taco_id, det.confidence) == ("farofa", None, 0.7)


def test_drops_invalid_grams_and_clamps_confidence(gemini):
    gemini(
        {
            "is_food": True,
            "items": [
                {"taco_id": 3, "name": "rice", "grams": 0, "confidence": 0.9},
                {"taco_id": 10, "name": "broccoli", "grams": 80, "confidence": 1.7},
            ],
        }
    )

    [det] = food_recognition.recognize_foods(b"img", "image/jpeg").detections

    assert (det.taco_id, det.confidence) == (10, 1.0)


def test_not_food_returns_empty(gemini):
    gemini({"is_food": False, "items": [{"taco_id": 3, "name": "x", "grams": 10, "confidence": 0.9}]})

    assert food_recognition.recognize_foods(b"img", "image/jpeg").detections == []


@pytest.mark.parametrize(
    "exc, transient",
    [
        (errors.APIError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), True),
        (errors.APIError(503, {"error": {"status": "UNAVAILABLE"}}), True),
        (errors.APIError(400, {"error": {"status": "INVALID_ARGUMENT"}}), False),
        (TimeoutError(), True),
        (ValueError("broken json"), False),
    ],
)
def test_is_transient_error(exc, transient):
    assert food_recognition.is_transient_error(exc) is transient


def test_taco_search_ignores_accents_and_case():
    assert [f.id for f in taco_table.search_foods("FEIJAO cozido")] == [561]
    assert [f.id for f in taco_table.search_foods("brocolis")] == [10]
