import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from PIL import Image, UnidentifiedImageError

from .config import Settings

logger = logging.getLogger(__name__)

# O ultralytics roda `pip install` sozinho quando acha que falta um pacote. Em servidor, nao.
# Precisa estar definido antes do primeiro import dele.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

STUB_MODEL_VERSION = "stub-yolo@0.1"


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


class Detector(Protocol):
    model_version: str

    def aquecer(self) -> None: ...

    def detectar(self, image_path: str) -> ResultadoInferencia: ...


def _abrir_imagem(image_path: str) -> Image.Image:
    try:
        img = Image.open(image_path)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"{image_path} nao parece uma imagem") from exc
    return img.convert("RGB")


class StubDetector:
    model_version = STUB_MODEL_VERSION

    def aquecer(self) -> None:
        pass

    def detectar(self, image_path: str) -> ResultadoInferencia:
        _abrir_imagem(image_path)

        return ResultadoInferencia(
            model_version=self.model_version,
            detections=[
                Deteccao("file de frango grelhado", 180.0, 0.82, {"x": 40, "y": 190, "w": 210, "h": 200}),
                Deteccao("arroz branco cozido", 150.0, 0.77, {"x": 190, "y": 240, "w": 180, "h": 190}),
                Deteccao("brocolis cozido", 90.0, 0.71, {"x": 250, "y": 200, "w": 160, "h": 210}),
            ],
        )


def _estimar_gramas(area_box: float, area_imagem: float, referencia: float) -> float:
    # Provisorio: proporcao da foto ocupada pelo alimento x um prato de referencia.
    # Trocar por volume/densidade por classe quando houver calibracao.
    if area_imagem <= 0:
        return 1.0
    return max(1.0, round(area_box / area_imagem * referencia, 2))


class YoloDetector:
    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int = 640,
        conf: float = 0.25,
        device: str = "cpu",
        plate_reference_grams: float = 600.0,
    ) -> None:
        from ultralytics import YOLO

        self._model = YOLO(str(model_path))
        self._imgsz = imgsz
        self._conf = conf
        self._device = device
        self._referencia = plate_reference_grams
        # O BackgroundTasks roda o worker no threadpool; o predict do Ultralytics nao e thread-safe.
        self._lock = threading.Lock()
        self.model_version = f"yolo:{Path(model_path).stem}"[:64]

    def _predict(self, img: Image.Image):
        with self._lock:
            return self._model.predict(
                img, imgsz=self._imgsz, conf=self._conf, device=self._device, verbose=False
            )

    def aquecer(self) -> None:
        self._predict(Image.new("RGB", (self._imgsz, self._imgsz)))

    def detectar(self, image_path: str) -> ResultadoInferencia:
        img = _abrir_imagem(image_path)
        largura, altura = img.size
        resultado = self._predict(img)[0]

        nomes = resultado.names
        deteccoes = []
        for xyxy, conf, cls in zip(
            resultado.boxes.xyxy.tolist(),
            resultado.boxes.conf.tolist(),
            resultado.boxes.cls.tolist(),
        ):
            x1, y1, x2, y2 = xyxy
            w, h = x2 - x1, y2 - y1
            deteccoes.append(
                Deteccao(
                    food=str(nomes[int(cls)]),
                    grams=_estimar_gramas(w * h, largura * altura, self._referencia),
                    confidence=round(float(conf), 4),
                    bbox={"x": round(x1), "y": round(y1), "w": round(w), "h": round(h)},
                )
            )

        return ResultadoInferencia(model_version=self.model_version, detections=deteccoes)


def carregar_detector(settings: Settings) -> Detector:
    if settings.model_path is None:
        logger.warning("sem NUTRIVISION_MODEL_PATH, usando o detector stub")
        return StubDetector()

    caminho = Path(settings.model_path)
    if not caminho.is_file():
        raise RuntimeError(f"pesos do modelo nao encontrados em {caminho}")
    try:
        import ultralytics  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "NUTRIVISION_MODEL_PATH definido mas o ultralytics nao esta instalado "
            '(pip install -e ".[vision]")'
        ) from exc

    logger.info("carregando modelo %s em %s", caminho, settings.model_device)
    return YoloDetector(
        caminho,
        imgsz=settings.model_imgsz,
        conf=settings.model_conf,
        device=settings.model_device,
        plate_reference_grams=settings.plate_reference_grams,
    )
