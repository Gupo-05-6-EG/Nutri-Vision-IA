from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NUTRIVISION_", env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    result_ttl_seconds: int = 24 * 3600
    max_upload_bytes: int = 10 * 1024 * 1024
    image_max_side: int = 1280
    jpeg_quality: int = 85

    gemini_api_key: str = ""
    # gemini-3.5-flash-lite respondeu 10 de 10 analises em 2-5 s na revisao de 18/11;
    # o gemini-3.8-flash deu 503 ("high demand") em todas as tentativas.
    gemini_model: str = "gemini-3.5-flash-lite"
    # Modelos de reserva, separados por virgula, tentados na mesma tentativa quando o
    # principal esta indisponivel (429, 5xx ou modelo inexistente para a conta).
    gemini_fallback_models: str = "gemini-3.5-flash"
    gemini_timeout_ms: int = 90_000
    taco_csv: Path = APP_DIR / "data" / "taco.csv"

    min_sharpness: float = 60.0
    min_brightness: float = 45.0
    max_brightness: float = 220.0
    min_confidence: float = 0.50

    @property
    def gemini_models(self) -> list:
        """Modelo principal seguido das reservas, sem repetir."""
        chain = [self.gemini_model] + [m.strip() for m in self.gemini_fallback_models.split(",")]
        return list(dict.fromkeys(m for m in chain if m))


settings = Settings()
