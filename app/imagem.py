from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pi_heif import register_heif_opener

from .config import settings

# Teto contra decompression bomb: ~40 MP cobre qualquer camera de celular.
Image.MAX_IMAGE_PIXELS = 40_000_000
# HEIC do iPhone. Tambem evita que o patch do ultralytics no Image.open tente instalar o pi-heif.
register_heif_opener()


class ImagemInvalidaError(Exception):
    pass


def _para_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        fundo = Image.new("RGB", rgba.size, (255, 255, 255))
        fundo.paste(rgba, mask=rgba.getchannel("A"))
        return fundo
    return img.convert("RGB")


def comprimir(conteudo: bytes) -> bytes:
    try:
        img = Image.open(BytesIO(conteudo))
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ImagemInvalidaError("arquivo nao e uma imagem valida") from exc

    # Aplica a rotacao da camera antes de descartar o EXIF.
    img = ImageOps.exif_transpose(img)
    img = _para_rgb(img)
    img.thumbnail((settings.image_max_side, settings.image_max_side), Image.Resampling.LANCZOS)

    saida = BytesIO()
    # Sem exif=: GPS e demais metadados nao vao para o disco.
    img.save(saida, "JPEG", quality=settings.jpeg_quality, optimize=True)
    return saida.getvalue()
