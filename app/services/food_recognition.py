from dataclasses import dataclass, field
from typing import Optional

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import settings
from app.services import taco_table

_PROMPT = """You are a nutritionist analyzing a photo of a meal.

1. Identify every food visible on the plate.
2. For each one, pick the closest item from the Brazilian TACO table below, taking the
   preparation into account (raw, cooked, grilled, fried...). Use ONLY ids from the list.
3. Estimate the grams of each food. Use a ~26 cm dinner plate, cutlery and glasses in the
   photo as size references.{plate_hint}
4. Give your confidence (0 to 1) in each identification.

Mixed preparations (Brazilian vinaigrette "vinagrete", mixed salads, farofa, stews...):
- if the table has the prepared dish itself, use it;
- otherwise list EACH visible ingredient as its own item with its own grams (for a
  vinagrete: tomato, onion, bell pepper...), instead of naming only the main one;
- keep the preparation right: raw chopped vegetables are raw ("cru"), never a
  steamed or cooked dish.

If the photo does not show food, answer is_food=false and an empty items list.

TACO table (id|name):
{table}
"""


class _GeminiItem(BaseModel):
    taco_id: int
    name: str
    grams: float
    confidence: float


class _GeminiResponse(BaseModel):
    is_food: bool
    items: list[_GeminiItem]


@dataclass(frozen=True)
class Detection:
    food: str
    taco_id: Optional[int]
    grams: float
    confidence: float


@dataclass(frozen=True)
class RecognitionResult:
    model_version: str
    detections: list = field(default_factory=list)


def is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))


def model_unavailable(exc: Exception) -> bool:
    """Erro em que vale tentar o proximo modelo da lista: sobrecarga, fora do ar ou
    modelo que nao existe (ou nao esta liberado) para esta chave."""
    if isinstance(exc, errors.APIError):
        return exc.code in (404, 429) or exc.code >= 500
    return False


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("NUTRIVISION_GEMINI_API_KEY is not set")
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=settings.gemini_timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _to_detections(response: _GeminiResponse) -> list:
    if not response.is_food:
        return []

    detections = []
    for item in response.items:
        if item.grams <= 0:
            continue
        confidence = min(max(item.confidence, 0.0), 1.0)
        food = taco_table.get_food(item.taco_id)
        if food is None:
            detections.append(Detection(item.name, None, item.grams, confidence))
        else:
            detections.append(Detection(food.name, food.id, item.grams, confidence))
    return detections


PLATE_HINTS = {
    "shallow": (
        "\n   The user says the food is on a SHALLOW (flat) plate: the portions are spread out,"
        "\n   so judge the amount by the area each food covers."
    ),
    "deep": (
        "\n   The user says the food is in a DEEP plate or bowl: part of the food is below the rim,"
        "\n   so the visible surface underestimates the volume - account for the depth."
    ),
}


def build_prompt(plate_type: Optional[str] = None) -> str:
    return _PROMPT.format(
        plate_hint=PLATE_HINTS.get(plate_type or "", ""), table=taco_table.format_for_prompt()
    )


def recognize_foods(
    image: bytes, mime_type: str, plate_type: Optional[str] = None
) -> RecognitionResult:
    """Pede a analise ao primeiro modelo disponivel da lista (principal e reservas).

    `model_version` registra o modelo que de fato respondeu. Se todos estiverem
    indisponiveis, o erro do ultimo sobe para a fila decidir se tenta de novo.
    """
    contents = [
        types.Part.from_bytes(data=image, mime_type=mime_type),
        build_prompt(plate_type),
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_GeminiResponse,
        temperature=0.2,
    )
    models = settings.gemini_models
    with _client() as client:
        for position, model in enumerate(models):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:
                if model_unavailable(exc) and position + 1 < len(models):
                    continue
                raise
            return RecognitionResult(
                model_version=model,
                detections=_to_detections(_GeminiResponse.model_validate_json(response.text)),
            )
    raise RuntimeError("no Gemini model configured")
