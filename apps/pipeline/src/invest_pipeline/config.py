from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest"
    provider_key: str = Field(
        default="fixture_dev",
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_PROVIDER_KEY",
            "provider_key",
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
