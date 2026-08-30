from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "invest-infra-v2"
    database_url: str = "postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest"
    api_cors_origins: str = (
        "http://localhost:3001,http://127.0.0.1:3001,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    stage4d_admission_commands_enabled: bool = False
    strategy_artifact_root: Path = Path("var/strategy-artifacts")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.api_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
