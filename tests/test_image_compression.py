import os
from io import BytesIO

import pytest
from PIL import Image

from app.core.config import settings
from app.services.image_compression import InvalidImageError, compress_image


def _make_image(size=(800, 600), fmt="PNG", mode="RGB", color=(200, 120, 40), **save_kwargs) -> bytes:
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, fmt, **save_kwargs)
    return buffer.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


def test_shrinks_longest_side_keeping_aspect_ratio():
    output = _open(compress_image(_make_image((4000, 3000))))

    assert output.format == "JPEG"
    assert output.size == (settings.image_max_side, settings.image_max_side * 3 // 4)


def test_does_not_upscale_small_images():
    output = _open(compress_image(_make_image((300, 200))))

    assert output.size == (300, 200)


def test_applies_exif_rotation_and_drops_metadata():
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "FakeCamera"
    original = _make_image((400, 200), fmt="JPEG", exif=exif.tobytes())

    output = _open(compress_image(original))

    assert output.size == (200, 400)
    assert len(output.getexif()) == 0


def test_png_with_alpha_becomes_rgb_on_white_background():
    original = _make_image((50, 50), mode="RGBA", color=(0, 0, 0, 0))

    output = _open(compress_image(original))

    assert output.mode == "RGB"
    assert min(output.getpixel((25, 25))) > 240


def test_rejects_bytes_that_are_not_an_image():
    with pytest.raises(InvalidImageError):
        compress_image(os.urandom(2048))
