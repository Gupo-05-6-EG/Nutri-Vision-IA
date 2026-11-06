from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api import analyses
from app.schemas import HealthOut
from app.worker import job_queue

DESCRIPTION = """
Analisa a foto de uma refeição e devolve os alimentos do prato, já identificados na
**Tabela Brasileira de Composição de Alimentos (TACO)**, com a quantidade estimada em gramas.

## Como funciona

1. `POST /api/v1/analyses` com a foto → devolve um `id`.
2. A foto é analisada em segundo plano pelo Google Gemini.
3. `GET /api/v1/analyses/{id}` até o status sair de `QUEUED` / `PROCESSING`.

O serviço só analisa: correções, confirmação da refeição e histórico ficam na API que o consome.
A foto nunca é guardada, e o resultado expira em 24 h.
"""

TAGS = [
    {"name": "analyses", "description": "Enviar a foto do prato e consultar os alimentos identificados."},
    {"name": "infra", "description": "Saúde do serviço."},
]

app = FastAPI(
    title="Nutri-Vision-IA",
    version="0.3.0",
    summary="Análise de fotos de refeições: alimentos da TACO com os gramas estimados",
    description=DESCRIPTION,
    openapi_tags=TAGS,
)


@app.exception_handler(RedisError)
async def _redis_unavailable(request: Request, exc: RedisError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "storage unavailable, try again"})


app.include_router(analyses.router, prefix="/api/v1")


@app.get(
    "/health",
    tags=["infra"],
    response_model=HealthOut,
    summary="Verificar a API e o Redis",
    responses={
        503: {
            "model": HealthOut,
            "description": "Redis fora do ar: envio de fotos e consulta de resultados indisponíveis.",
            "content": {"application/json": {"example": {"status": "degraded", "redis": "down"}}},
        }
    },
)
def health() -> JSONResponse:
    try:
        job_queue.get_redis().ping()
    except RedisError:
        return JSONResponse(status_code=503, content={"status": "degraded", "redis": "down"})
    return JSONResponse(content={"status": "ok", "redis": "ok"})
