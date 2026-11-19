import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.services import food_recognition


class _FakeClient:
    def __init__(self, response: dict, failures: dict = None):
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._text = json.dumps(response)
        self._failures = failures or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] in self._failures:
            raise self._failures[kwargs["model"]]
        return SimpleNamespace(text=self._text)


@pytest.fixture
def gemini(monkeypatch):
    def _install(response: dict, failures: dict = None) -> _FakeClient:
        fake = _FakeClient(response, failures)
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
    assert fake.closed


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
        (httpx.ReadTimeout("timed out"), True),
        (httpx.ConnectError("refused"), True),
        (ValueError("broken json"), False),
    ],
)
def test_is_transient_error(exc, transient):
    assert food_recognition.is_transient_error(exc) is transient


RICE = {"is_food": True, "items": [{"taco_id": 3, "name": "rice", "grams": 150, "confidence": 0.9}]}
UNAVAILABLE = errors.APIError(503, {"error": {"status": "UNAVAILABLE"}})


@pytest.fixture
def two_models(monkeypatch):
    monkeypatch.setattr(food_recognition.settings, "gemini_model", "principal")
    monkeypatch.setattr(food_recognition.settings, "gemini_fallback_models", "reserva, principal")


def test_default_model_is_flash_lite():
    from app.core.config import Settings

    assert Settings(_env_file=None).gemini_model == "gemini-3.5-flash-lite"


def test_model_chain_has_no_duplicates(two_models):
    assert food_recognition.settings.gemini_models == ["principal", "reserva"]


def test_uses_the_main_model_when_it_answers(gemini, two_models):
    fake = gemini(RICE)

    result = food_recognition.recognize_foods(b"img", "image/jpeg")

    assert result.model_version == "principal"
    assert [c["model"] for c in fake.calls] == ["principal"]


@pytest.mark.parametrize("code", [404, 429, 503, 504])
def test_falls_back_when_the_main_model_is_unavailable(gemini, two_models, code):
    fake = gemini(RICE, failures={"principal": errors.APIError(code, {"error": {}})})

    result = food_recognition.recognize_foods(b"img", "image/jpeg")

    assert result.model_version == "reserva"
    assert [c["model"] for c in fake.calls] == ["principal", "reserva"]
    assert result.detections[0].taco_id == 3


def test_raises_when_every_model_is_unavailable(gemini, two_models):
    gemini(RICE, failures={"principal": UNAVAILABLE, "reserva": UNAVAILABLE})

    with pytest.raises(errors.APIError):
        food_recognition.recognize_foods(b"img", "image/jpeg")


def test_bad_request_does_not_fall_back(gemini, two_models):
    fake = gemini(RICE, failures={"principal": errors.APIError(400, {"error": {}})})

    with pytest.raises(errors.APIError):
        food_recognition.recognize_foods(b"img", "image/jpeg")
    assert [c["model"] for c in fake.calls] == ["principal"]


def test_prompt_asks_to_split_mixed_dishes(gemini):
    fake = gemini(RICE)

    food_recognition.recognize_foods(b"img", "image/jpeg")

    prompt = fake.calls[0]["contents"][1]
    assert "vinagrete" in prompt
    assert "EACH visible ingredient" in prompt
    assert "SHALLOW" not in prompt and "DEEP plate" not in prompt


@pytest.mark.parametrize(("plate_type", "hint"), [("shallow", "SHALLOW"), ("deep", "DEEP plate")])
def test_plate_type_becomes_a_hint(gemini, plate_type, hint):
    fake = gemini(RICE)

    food_recognition.recognize_foods(b"img", "image/jpeg", plate_type=plate_type)

    assert hint in fake.calls[0]["contents"][1]
