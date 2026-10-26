import io
from dataclasses import dataclass, field

from PIL import Image, ImageFilter, ImageStat

from app.core.config import settings

ANALYSIS_SIDE = 512

_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)

ISSUE_BLURRY = "blurry"
ISSUE_TOO_DARK = "too_dark"
ISSUE_TOO_BRIGHT = "too_bright"


class UnreadableImageError(Exception):
    pass


@dataclass(frozen=True)
class ImageQuality:
    sharpness: float
    brightness: float
    issues: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict:
        return {
            "sharpness": self.sharpness,
            "brightness": self.brightness,
            "issues": list(self.issues),
            "ok": self.ok,
        }


def assess_image(image_bytes: bytes) -> ImageQuality:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            gray = image.convert("L")
    except OSError as exc:
        raise UnreadableImageError(str(exc)) from exc

    gray.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE))
    sharpness = round(ImageStat.Stat(gray.filter(_LAPLACIAN)).var[0], 1)
    brightness = round(ImageStat.Stat(gray).mean[0], 1)

    issues = []
    if sharpness < settings.min_sharpness:
        issues.append(ISSUE_BLURRY)
    if brightness < settings.min_brightness:
        issues.append(ISSUE_TOO_DARK)
    elif brightness > settings.max_brightness:
        issues.append(ISSUE_TOO_BRIGHT)

    return ImageQuality(sharpness=sharpness, brightness=brightness, issues=issues)
