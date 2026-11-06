"""Configuración central (lee .env). La llave de DeepSeek nunca se guarda en BD ni se expone."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    data_dir: Path = Path("./data")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_vision_model: str = "deepseek-flash"
    # razonamiento al traducir: disabled | low | high | max (high = máxima calidad, más lento)
    deepseek_thinking: str = "high"

    # traductor falso (sin API) para probar la maquetación y la interfaz sin gastar tokens
    fake_translator: bool = False
    cors_origins: str = "http://localhost:3000"

    max_upload_mb: int = 200
    translation_concurrency: int = 10
    translation_batch_chars: int = 3000
    translation_batch_max_segments: int = 40

    # Ajuste de texto: nunca por debajo de estos límites; si no cabe → revisión
    min_font_scale: float = 0.75
    min_font_size_pt: float = 5.5

    # Directorios de fuentes separados por ':' o ';'
    fonts_dirs: str = "./fonts"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
