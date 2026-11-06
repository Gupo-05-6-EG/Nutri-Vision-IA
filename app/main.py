from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api import analyses
from app.worker import job_queue

app = FastAPI(
    title="Nutri-Vision-IA",
    version="0.3.0",
    summary="Meal photo analysis: foods from the TACO table with estimated grams",
)


@app.exception_handler(RedisError)
async def _redis_unavailable(request: Request, exc: RedisError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "storage unavailable, try again"})


app.include_router(analyses.router, prefix="/api/v1")


@app.get("/health", tags=["infra"])
def health() -> JSONResponse:
    try:
        job_queue.get_redis().ping()
    except RedisError:
        return JSONResponse(status_code=503, content={"status": "degraded", "redis": "down"})
    return JSONResponse(content={"status": "ok", "redis": "ok"})
