import uuid

from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas import AnalysisCreatedOut, AnalysisOut, ErrorOut
from app.services import image_compression, image_quality
from app.services.analysis_result import REASON_BAD_PHOTO, AnalysisStatus
from app.worker import job_queue, result_store

router = APIRouter(prefix="/analyses", tags=["analyses"])

ANALYSIS_ID = "8c839452-3b71-4c47-9e97-34f14ac7d5ea"


def _json_examples(**examples) -> dict:
    return {"application/json": {"examples": examples}}


def _error(description: str, detail: str) -> dict:
    return {"model": ErrorOut, "description": description, "content": {"application/json": {"example": {"detail": detail}}}}


CREATE_RESPONSES = {
    202: {
        "description": "Foto aceita. Foto boa vai para a fila; foto ruim é respondida na hora.",
        "content": _json_examples(
            queued={
                "summary": "Foto na fila para análise",
                "value": {"id": ANALYSIS_ID, "status": "QUEUED"},
            },
            bad_photo={
                "summary": "Foto borrada ou mal iluminada (o Gemini não é chamado)",
                "value": {"id": ANALYSIS_ID, "status": "NOT_ESTIMATED", "reason": "bad_photo", "issues": ["blurry"]},
            },
        ),
    },
    413: _error("Foto maior que o limite de upload (10 MB por padrão).", "image larger than 10485760 bytes"),
    415: _error("O arquivo não é uma imagem ou não pôde ser aberto.", "file is not a valid image"),
    503: _error("Redis fora do ar. Tente novamente mais tarde.", "analysis queue unavailable, try again"),
}

GET_RESPONSES = {
    200: {
        "description": "Situação atual da análise. Consulte de novo enquanto o status for `QUEUED` ou `PROCESSING`.",
        "content": _json_examples(
            done={
                "summary": "Alimentos identificados",
                "value": {
                    "id": ANALYSIS_ID,
                    "status": "DONE",
                    "model_version": "gemini-3.5-flash-lite",
                    "items": [
                        {"food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 160.0, "confidence": 0.95},
                        {"food": "Feijão, preto, cozido", "taco_id": 567, "grams": 110.0, "confidence": 0.95},
                        {"food": "farofa", "grams": 30.0, "confidence": 0.7},
                    ],
                },
            },
            processing={
                "summary": "Ainda em análise",
                "value": {"id": ANALYSIS_ID, "status": "PROCESSING"},
            },
            bad_photo={
                "summary": "Foto ruim",
                "value": {"id": ANALYSIS_ID, "status": "NOT_ESTIMATED", "reason": "bad_photo", "issues": ["blurry"], "items": []},
            },
            nothing_detected={
                "summary": "Nenhum alimento na foto",
                "value": {"id": ANALYSIS_ID, "status": "NOT_ESTIMATED", "reason": "nothing_detected", "model_version": "gemini-3.5-flash-lite", "items": []},
            },
            failed={
                "summary": "O Gemini falhou mesmo depois das novas tentativas",
                "value": {
                    "id": ANALYSIS_ID,
                    "status": "FAILED",
                    "error": "ServerError: 503 UNAVAILABLE. This model is currently experiencing high demand.",
                },
            },
        ),
    },
    404: _error("Não existe análise com esse id, ou o resultado já expirou (24 h).", "analysis not found"),
    503: _error("Redis fora do ar. Tente novamente mais tarde.", "storage unavailable, try again"),
}


def _read_upload(file: UploadFile) -> bytes:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="send an image file",
        )

    content = file.file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"image larger than {settings.max_upload_bytes} bytes",
        )
    return content


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalysisCreatedOut,
    response_model_exclude_none=True,
    summary="Enviar a foto do prato",
    description=(
        "Envia a foto para análise e devolve na hora o `id` da análise.\n\n"
        "A foto é comprimida (rotação do EXIF, até 1280 px, JPEG sem metadados) e passa por uma checagem "
        "de nitidez e luminosidade. Foto ruim é respondida na hora como `NOT_ESTIMATED` e nem chega ao Gemini. "
        "Foto boa vai para a fila: consulte `GET /api/v1/analyses/{id}` para pegar o resultado.\n\n"
        "A foto não é guardada: ela existe só dentro do job da fila e é apagada quando a análise termina."
    ),
    responses=CREATE_RESPONSES,
)
def create_analysis(
    file: UploadFile = File(description="Foto da refeição: JPEG, PNG, WebP, HEIC ou outro formato que o Pillow abra. Até 10 MB."),
    plate_type: Optional[Literal["shallow", "deep"]] = Form(
        default=None,
        description="Tipo de prato informado pelo usuário (raso ou fundo): vira uma dica para estimar as gramas.",
    ),
) -> AnalysisCreatedOut:
    try:
        image = image_compression.compress_image(_read_upload(file))
    except image_compression.InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))

    quality = image_quality.assess_image(image)
    analysis_id = str(uuid.uuid4())

    if not quality.ok:
        analysis = {
            "id": analysis_id,
            "status": AnalysisStatus.NOT_ESTIMATED.value,
            "reason": REASON_BAD_PHOTO,
            "issues": list(quality.issues),
            "items": [],
        }
        result_store.save(analysis)
        return AnalysisCreatedOut(**analysis)

    result_store.save({"id": analysis_id, "status": AnalysisStatus.QUEUED.value})
    try:
        job_queue.enqueue_analysis(
            analysis_id, image, image_compression.COMPRESSED_MIME_TYPE, plate_type
        )
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analysis queue unavailable, try again",
        )
    return AnalysisCreatedOut(id=analysis_id, status=AnalysisStatus.QUEUED)


@router.get(
    "/{analysis_id}",
    response_model=AnalysisOut,
    response_model_exclude_none=True,
    summary="Consultar o resultado da análise",
    description=(
        "Devolve os alimentos identificados na foto, com o id da TACO e os gramas estimados.\n\n"
        "Enquanto o status for `QUEUED` ou `PROCESSING`, consulte de novo em alguns segundos. "
        "Campos sem valor não aparecem. O resultado expira 24 h depois do envio."
    ),
    responses=GET_RESPONSES,
)
def get_analysis(
    analysis_id: str = Path(description="Id devolvido pelo `POST /api/v1/analyses`.", examples=[ANALYSIS_ID]),
) -> AnalysisOut:
    analysis = result_store.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis not found")
    return AnalysisOut(**analysis)
