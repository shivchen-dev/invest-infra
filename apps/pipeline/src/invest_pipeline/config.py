from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest"
    provider_key: str = Field(
        default="fixture_dev",
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_PROVIDER_KEY",
            "provider_key",
        ),
    )
    personal_universe_path: Path = Field(
        default=_REPOSITORY_ROOT / "config" / "personal-universe.yaml",
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH",
            "personal_universe_path",
        ),
    )
    candidate_pool_policy_path: Path = Field(
        default=_REPOSITORY_ROOT / "config" / "candidate-pool-personal.yaml",
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH",
            "candidate_pool_policy_path",
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
