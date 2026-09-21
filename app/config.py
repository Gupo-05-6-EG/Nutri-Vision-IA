from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NUTRIVISION_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'nutrivision.db'}"
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    grams_epsilon: float = 0.5


settings = Settings()
