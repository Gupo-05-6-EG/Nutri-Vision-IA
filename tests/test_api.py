from pathlib import Path

from PIL import Image

from app.config import settings
from app.db import SessionLocal
from app.models import Analysis
from app.vision import STUB_MODEL_VERSION

from .conftest import gerar_imagem


def test_upload_comprime_e_processa_com_detector_carregado(client):
    original = gerar_imagem((3000, 2000))

    resp = client.post(
        "/api/v1/analises",
        files={"file": ("prato.png", original, "image/png")},
        data={"meal_type": "almoco"},
    )
    assert resp.status_code == 202
    analysis_id = resp.json()["id"]

    # O TestClient roda as background tasks antes de devolver a resposta.
    corpo = client.get(f"/api/v1/analises/{analysis_id}").json()
    assert corpo["status"] == "DONE"
    assert corpo["model_version"] == STUB_MODEL_VERSION
    assert len(corpo["itens"]) == 3

    with SessionLocal() as db:
        caminho = Path(db.get(Analysis, analysis_id).image_path)
    assert caminho.suffix == ".jpg"
    assert caminho.parent == settings.upload_dir
    assert caminho.stat().st_size < len(original)
    with Image.open(caminho) as salvo:
        assert salvo.format == "JPEG"
        assert max(salvo.size) == settings.image_max_side


def test_upload_de_arquivo_que_nao_e_imagem(client):
    resp = client.post(
        "/api/v1/analises",
        files={"file": ("prato.jpg", b"isto nao e uma foto", "image/jpeg")},
    )

    assert resp.status_code == 415


def test_health_informa_o_modelo_carregado(client):
    resp = client.get("/health")

    assert resp.json() == {"status": "ok", "model_version": STUB_MODEL_VERSION}
