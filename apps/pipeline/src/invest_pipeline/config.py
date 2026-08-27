from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    stock_universe_path: Path = Field(
        default=_REPOSITORY_ROOT / "config" / "stock-universe.yaml",
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_STOCK_UNIVERSE_PATH",
            "stock_universe_path",
        ),
    )
    workbuddy_bridge_root: Path = Field(
        default=Path("/shared/workbuddy"),
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_WORKBUDDY_BRIDGE_ROOT",
            "workbuddy_bridge_root",
        ),
    )
    workbuddy_source_dir: Path = Field(
        default=Path("/shared/workbuddy/candidate/results"),
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_WORKBUDDY_SOURCE_DIR",
            "workbuddy_source_dir",
        ),
    )
    strategy_approver_agent_ids: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices(
            "INVEST_PIPELINE_STRATEGY_APPROVER_AGENT_IDS",
            "strategy_approver_agent_ids",
        ),
    )

    @field_validator("strategy_approver_agent_ids", mode="after")
    @classmethod
    def _normalize_strategy_approver_agent_ids(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise TypeError(
                    "strategy_approver_agent_ids entries must be strings, "
                    f"got {type(raw).__name__}"
                )
            stripped = raw.strip()
            if not stripped:
                raise ValueError(
                    "strategy_approver_agent_ids entries must be non-empty "
                    "strings; blank or whitespace-only values are rejected so "
                    "authorization cannot be silently granted"
                )
            normalized.append(stripped)
        return tuple(normalized)

    @model_validator(mode="after")
    def derive_workbuddy_source_dir(self) -> Settings:
        if "workbuddy_source_dir" not in self.model_fields_set:
            self.workbuddy_source_dir = self.workbuddy_bridge_root / "candidate" / "results"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
