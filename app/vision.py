from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MODEL_VERSION = "stub-yolo@0.1"

_ASSINATURAS = (
    bytes.fromhex("ffd8ff"),
    bytes.fromhex("89504e470d0a1a0a"),
    b"BM",
    b"GIF8",
    b"RIFF",
)


@dataclass(frozen=True)
class Deteccao:
    food: str
    grams: float
    confidence: float
    bbox: Optional[dict] = None


@dataclass(frozen=True)
class ResultadoInferencia:
    model_version: str
    detections: list = field(default_factory=list)


def _ler_imagem(image_path: str) -> bytes:
    dados = Path(image_path).read_bytes()
    if not dados.startswith(_ASSINATURAS):
        raise ValueError(f"{image_path} nao parece uma imagem")
    return dados


def detectar(image_path: str) -> ResultadoInferencia:
    _ler_imagem(image_path)

    return ResultadoInferencia(
        model_version=MODEL_VERSION,
        detections=[
            Deteccao("file de frango grelhado", 180.0, 0.82, {"x": 40, "y": 190, "w": 210, "h": 200}),
            Deteccao("arroz branco cozido", 150.0, 0.77, {"x": 190, "y": 240, "w": 180, "h": 190}),
            Deteccao("brocolis cozido", 90.0, 0.71, {"x": 250, "y": 200, "w": 160, "h": 210}),
        ],
    )
