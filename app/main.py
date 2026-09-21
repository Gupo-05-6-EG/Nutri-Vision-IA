import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from . import service
from .config import settings
from .db import create_all, get_db
from .schemas import (
    AnalysisCreatedOut,
    AnalysisOut,
    ConfirmIn,
    ItemOut,
    ItemPatchIn,
    ManualItemIn,
)
from .worker import processar_analise


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    create_all()
    yield


app = FastAPI(
    title="Nutri-Vision-IA",
    version="0.1.0",
    summary="Analise de prato por imagem com rastreabilidade IA vs confirmado (RF23)",
    lifespan=lifespan,
)

router = APIRouter(prefix="/api/v1", tags=["analises"])


@app.exception_handler(service.NotFoundError)
async def _nao_encontrado(request: Request, exc: service.NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(service.ConflictError)
async def _conflito(request: Request, exc: service.ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def _salvar_imagem(file: UploadFile) -> Path:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="envie um arquivo de imagem",
        )

    conteudo = file.file.read(settings.max_upload_bytes + 1)
    if not conteudo:
        raise HTTPException(status_code=422, detail="arquivo vazio")
    if len(conteudo) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"imagem acima de {settings.max_upload_bytes} bytes",
        )

    sufixo = Path(file.filename or "").suffix.lower() or ".jpg"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    destino = settings.upload_dir / f"{uuid.uuid4()}{sufixo}"
    destino.write_bytes(conteudo)
    return destino


@router.post(
    "/analises",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalysisCreatedOut,
    summary="Envia a foto do prato para a fila de analise",
)
def criar_analise(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(default=None),
    meal_type: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
) -> AnalysisCreatedOut:
    caminho = _salvar_imagem(file)
    analysis = service.create_analysis(
        db, image_path=str(caminho), patient_id=patient_id, meal_type=meal_type
    )
    background.add_task(processar_analise, analysis.id)
    return AnalysisCreatedOut(id=analysis.id, status=analysis.status)


@router.get(
    "/analises/{analysis_id}",
    response_model=AnalysisOut,
    summary="Resultado da analise: estimativa da IA lado a lado com o confirmado",
)
def obter_analise(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisOut:
    return AnalysisOut.from_model(service.get_analysis(db, analysis_id))


@router.patch(
    "/analises/{analysis_id}/itens/{item_id}",
    response_model=ItemOut,
    summary="Corrige o alimento e/ou os gramas de um item",
)
def corrigir_item(
    analysis_id: str,
    item_id: str,
    patch: ItemPatchIn,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(service.update_item(db, analysis_id, item_id, patch))


@router.post(
    "/analises/{analysis_id}/itens",
    status_code=status.HTTP_201_CREATED,
    response_model=ItemOut,
    summary="Adiciona um alimento que a IA nao detectou",
)
def adicionar_item(
    analysis_id: str,
    data: ManualItemIn,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(service.add_manual_item(db, analysis_id, data))


@router.delete(
    "/analises/{analysis_id}/itens/{item_id}",
    response_model=ItemOut,
    summary="Remove um item do calculo (soft delete, preserva a estimativa)",
)
def remover_item(
    analysis_id: str,
    item_id: str,
    actor: Optional[str] = None,
    db: Session = Depends(get_db),
) -> ItemOut:
    return ItemOut.from_model(service.remove_item(db, analysis_id, item_id, actor))


@router.post(
    "/analises/{analysis_id}/confirmar",
    response_model=AnalysisOut,
    summary="Fecha a refeicao, aceitando correcoes em lote",
)
def confirmar_analise(
    analysis_id: str,
    payload: Optional[ConfirmIn] = None,
    db: Session = Depends(get_db),
) -> AnalysisOut:
    return AnalysisOut.from_model(
        service.confirm_analysis(db, analysis_id, payload or ConfirmIn())
    )


app.include_router(router)


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"status": "ok"}
