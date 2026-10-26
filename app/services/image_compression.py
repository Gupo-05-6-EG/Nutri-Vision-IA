from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pi_heif import register_heif_opener

from app.core.config import settings

COMPRESSED_MIME_TYPE = "image/jpeg"

Image.MAX_IMAGE_PIXELS = 40_000_000
register_heif_opener()


class InvalidImageError(Exception):
    pass


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def compress_image(content: bytes) -> bytes:
    try:
        image = Image.open(BytesIO(content))
        image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise InvalidImageError("file is not a valid image") from exc

    image = ImageOps.exif_transpose(image)
    image = _to_rgb(image)
    image.thumbnail((settings.image_max_side, settings.image_max_side), Image.Resampling.LANCZOS)

    output = BytesIO()
    image.save(output, "JPEG", quality=settings.jpeg_quality, optimize=True)
    return output.getvalue()
