from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.analysis_result import AnalysisStatus


class ItemOut(BaseModel):
    food: str = Field(
        description=(
            "Nome do alimento como está na Tabela TACO (ou o nome dado pelo Gemini, quando não está na tabela)."
        ),
        examples=["Arroz, tipo 1, cozido"],
    )
    taco_id: Optional[int] = Field(
        default=None,
        description="Id do alimento na Tabela TACO. Não aparece quando o Gemini não encontrou o alimento na tabela.",
        examples=[3],
    )
    grams: float = Field(description="Quantidade estimada no prato, em gramas.", examples=[160.0])
    confidence: float = Field(
        ge=0, le=1, description="Confiança do modelo na identificação do alimento, de 0 a 1.", examples=[0.95]
    )


class AnalysisCreatedOut(BaseModel):
    id: str = Field(
        description="Id da análise. Use para consultar o resultado.",
        examples=["8c839452-3b71-4c47-9e97-34f14ac7d5ea"],
    )
    status: AnalysisStatus = Field(
        description=(
            "`QUEUED`: na fila, aguardando o worker. `PROCESSING`: o Gemini está analisando. "
            "`DONE`: alimentos identificados. `NOT_ESTIMATED`: não deu para estimar nada confiável (ver `reason`). "
            "`FAILED`: erro no Gemini mesmo depois das novas tentativas (ver `error`)."
        ),
        examples=["QUEUED"],
    )
    reason: Optional[str] = Field(
        default=None,
        description="Só quando `NOT_ESTIMATED`: `bad_photo`, `nothing_detected` ou `low_confidence`.",
        examples=["bad_photo"],
    )
    issues: Optional[list[str]] = Field(
        default=None,
        description=(
            "Só quando `reason` é `bad_photo`: `blurry` (borrada), `too_dark` (escura) e/ou `too_bright` (estourada)."
        ),
        examples=[["blurry"]],
    )


class AnalysisOut(AnalysisCreatedOut):
    model_config = ConfigDict(protected_namespaces=())

    error: Optional[str] = Field(
        default=None,
        description="Só quando `FAILED`: o que deu errado.",
        examples=["ServerError: 503 UNAVAILABLE. This model is currently experiencing high demand."],
    )
    model_version: Optional[str] = Field(
        default=None, description="Modelo do Gemini que fez a análise.", examples=["gemini-3.5-flash"]
    )
    items: Optional[list[ItemOut]] = Field(
        default=None,
        description="Alimentos encontrados no prato. Aparece quando o status é `DONE` ou `NOT_ESTIMATED`.",
    )


class ErrorOut(BaseModel):
    detail: str = Field(description="Mensagem de erro.", examples=["analysis not found"])


class HealthOut(BaseModel):
    status: str = Field(description="`ok` ou `degraded`.", examples=["ok"])
    redis: str = Field(description="`ok` ou `down`.", examples=["ok"])
