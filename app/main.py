from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api import analyses, foods
from app.core.database import create_all
from app.services import analysis_service, taco_table
from app.worker import job_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(
    title="Nutri-Vision-IA",
    version="0.2.0",
    summary="Meal photo analysis with AI vs confirmed traceability (RF23)",
    lifespan=lifespan,
)


@app.exception_handler(analysis_service.NotFoundError)
async def _not_found(request: Request, exc: analysis_service.NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(analysis_service.ConflictError)
async def _conflict(request: Request, exc: analysis_service.ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(analysis_service.InvalidInputError)
async def _invalid_input(request: Request, exc: analysis_service.InvalidInputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(taco_table.TacoTableUnavailableError)
async def _taco_unavailable(
    request: Request, exc: taco_table.TacoTableUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(analyses.router, prefix="/api/v1")
app.include_router(foods.router, prefix="/api/v1")


@app.get("/health", tags=["infra"])
def health() -> JSONResponse:
    try:
        job_queue.get_redis().ping()
    except RedisError:
        return JSONResponse(status_code=503, content={"status": "degraded", "redis": "down"})
    return JSONResponse(content={"status": "ok", "redis": "ok"})
