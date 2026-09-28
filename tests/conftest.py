import os
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

# O settings e instanciado no import do app: o ambiente precisa estar pronto antes.
_TMP = Path(tempfile.mkdtemp(prefix="nutrivision-tests-"))
os.environ["NUTRIVISION_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["NUTRIVISION_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ.pop("NUTRIVISION_MODEL_PATH", None)

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def gerar_imagem(tamanho=(800, 600), formato="PNG", modo="RGB", cor=(200, 120, 40), **save_kwargs) -> bytes:
    img = Image.new(modo, tamanho, cor)
    buf = BytesIO()
    img.save(buf, formato, **save_kwargs)
    return buf.getvalue()
