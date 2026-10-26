from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NUTRIVISION_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'nutrivision.db'}"
    redis_url: str = "redis://localhost:6379/0"
    max_upload_bytes: int = 10 * 1024 * 1024

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    taco_csv: Path = APP_DIR / "data" / "taco.csv"

    grams_epsilon: float = 0.5

    min_sharpness: float = 60.0
    min_brightness: float = 45.0
    max_brightness: float = 220.0
    min_confidence: float = 0.50


settings = Settings()
