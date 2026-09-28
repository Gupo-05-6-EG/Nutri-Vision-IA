from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NUTRIVISION_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    database_url: str = f"sqlite:///{BASE_DIR / 'nutrivision.db'}"
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    grams_epsilon: float = 0.5

    # Compressao no upload: o YOLO trabalha em ~640px, guardar mais que isso so gasta disco.
    image_max_side: int = 1280
    jpeg_quality: int = 85

    # Sem pesos configurados o app sobe com o detector stub.
    model_path: Optional[Path] = None
    model_imgsz: int = 640
    model_conf: float = 0.25
    model_device: str = "cpu"

    # Heuristica provisoria area -> gramas: um box que cobre a foto inteira vale isso.
    plate_reference_grams: float = 600.0


settings = Settings()
