"""BaoStock adapter configuration (Slice-1 of PR-08)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

_ADJUSTFLAG_NONE = "3"


class BaostockSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the BaoStock adapter."""

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_BAOSTOCK_",
        extra="ignore",
    )

    enabled: bool = False
    adjustflag: str = _ADJUSTFLAG_NONE

    def model_post_init(self, __context: object) -> None:
        if self.adjustflag != _ADJUSTFLAG_NONE:
            raise ValueError(
                "BaostockSettings.adjustflag must be '3' (the BaoStock "
                "'no adjustment' literal); ADR-0005 §4 forbids any "
                f"non-NONE adjustment reaching the production pipeline. "
                f"got {self.adjustflag!r}"
            )


__all__ = ["BaostockSettings"]
