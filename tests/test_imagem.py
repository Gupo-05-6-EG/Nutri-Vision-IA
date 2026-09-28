import os
from io import BytesIO

import pytest
from PIL import Image

from app.config import settings
from app.imagem import ImagemInvalidaError, comprimir

from .conftest import gerar_imagem


def _abrir(dados: bytes) -> Image.Image:
    return Image.open(BytesIO(dados))


def test_reduz_lado_maior_mantendo_proporcao():
    saida = _abrir(comprimir(gerar_imagem((4000, 3000))))

    assert saida.format == "JPEG"
    assert saida.size == (settings.image_max_side, settings.image_max_side * 3 // 4)


def test_nao_amplia_imagem_pequena():
    saida = _abrir(comprimir(gerar_imagem((300, 200))))

    assert saida.size == (300, 200)


def test_aplica_rotacao_exif_e_descarta_metadados():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: girar 90 graus
    exif[0x010F] = "CameraFake"  # Make
    original = gerar_imagem((400, 200), formato="JPEG", exif=exif.tobytes())

    saida = _abrir(comprimir(original))

    assert saida.size == (200, 400)
    assert len(saida.getexif()) == 0


def test_png_com_alfa_vira_rgb_com_fundo_branco():
    original = gerar_imagem((50, 50), modo="RGBA", cor=(0, 0, 0, 0))

    saida = _abrir(comprimir(original))

    assert saida.mode == "RGB"
    r, g, b = saida.getpixel((25, 25))
    assert min(r, g, b) > 240


def test_bytes_que_nao_sao_imagem():
    with pytest.raises(ImagemInvalidaError):
        comprimir(os.urandom(2048))


def test_bytes_que_nao_sao_imagem_com_patch_do_ultralytics_ativo():
    # O ultralytics troca o PIL.Image.open globalmente; o erro tem que continuar sendo 415.
    pytest.importorskip("ultralytics.utils.patches")

    with pytest.raises(ImagemInvalidaError):
        comprimir(os.urandom(2048))
