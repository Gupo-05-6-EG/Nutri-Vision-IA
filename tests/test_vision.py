import sys
import types

import pytest
from PIL import Image

from app import vision
from app.config import Settings


class _Tensor:
    def __init__(self, dados):
        self._dados = dados

    def tolist(self):
        return self._dados


class _FakeYOLO:
    instancias = []

    def __init__(self, caminho):
        self.caminho = caminho
        self.chamadas = []
        _FakeYOLO.instancias.append(self)

    def predict(self, img, **kwargs):
        self.chamadas.append((img.size, kwargs))
        boxes = types.SimpleNamespace(
            xyxy=_Tensor([[0.0, 0.0, 50.0, 50.0], [10.0, 20.0, 10.2, 20.2]]),
            conf=_Tensor([0.91234, 0.3]),
            cls=_Tensor([0.0, 1.0]),
        )
        return [types.SimpleNamespace(boxes=boxes, names={0: "broccoli", 1: "pizza"})]


@pytest.fixture
def fake_ultralytics(monkeypatch):
    _FakeYOLO.instancias.clear()
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=_FakeYOLO))
    return _FakeYOLO


@pytest.fixture
def pesos(tmp_path):
    caminho = tmp_path / "comida-v1.pt"
    caminho.write_bytes(b"pesos")
    return caminho


def test_yolo_converte_boxes_em_deteccoes(fake_ultralytics, pesos, tmp_path):
    foto = tmp_path / "prato.jpg"
    Image.new("RGB", (100, 100)).save(foto)
    detector = vision.YoloDetector(pesos, imgsz=320, conf=0.4, plate_reference_grams=600.0)

    resultado = detector.detectar(str(foto))

    assert resultado.model_version == "yolo:comida-v1"
    grande, minusculo = resultado.detections
    assert grande.food == "broccoli"
    assert grande.bbox == {"x": 0, "y": 0, "w": 50, "h": 50}
    assert grande.grams == 150.0  # 1/4 da foto x 600 g
    assert grande.confidence == 0.9123
    assert minusculo.food == "pizza"
    assert minusculo.grams == 1.0  # nunca zero: DetectionIn exige grams > 0

    _, kwargs = fake_ultralytics.instancias[0].chamadas[-1]
    assert kwargs["imgsz"] == 320 and kwargs["conf"] == 0.4 and kwargs["verbose"] is False


def test_aquecer_roda_um_predict_no_tamanho_do_modelo(fake_ultralytics, pesos):
    detector = vision.YoloDetector(pesos, imgsz=320)

    detector.aquecer()

    assert fake_ultralytics.instancias[0].chamadas[0][0] == (320, 320)


def test_carregar_detector_sem_pesos_usa_stub():
    detector = vision.carregar_detector(Settings(model_path=None))

    assert isinstance(detector, vision.StubDetector)


def test_carregar_detector_carrega_o_modelo_uma_vez(fake_ultralytics, pesos):
    detector = vision.carregar_detector(Settings(model_path=pesos))

    assert isinstance(detector, vision.YoloDetector)
    assert len(fake_ultralytics.instancias) == 1


def test_carregar_detector_com_pesos_inexistentes_falha(tmp_path):
    with pytest.raises(RuntimeError, match="nao encontrados"):
        vision.carregar_detector(Settings(model_path=tmp_path / "nao-existe.pt"))


def test_carregar_detector_sem_ultralytics_falha(monkeypatch, pesos):
    monkeypatch.setitem(sys.modules, "ultralytics", None)

    with pytest.raises(RuntimeError, match="ultralytics"):
        vision.carregar_detector(Settings(model_path=pesos))
