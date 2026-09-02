"""BaoStock adapter configuration (Slice-1 of PR-08)."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADJUSTFLAG_NONE = "3"
_DEFAULT_MAX_HISTORY_DAYS = 120


class BaostockSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the BaoStock adapter."""

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_BAOSTOCK_",
        extra="ignore",
    )

    enabled: bool = False
    adjustflag: str = _ADJUSTFLAG_NONE
    # ``max_history_days`` is a plain ``int`` so ``BaseSettings`` can
    # parse the environment string ``INVEST_PIPELINE_BAOSTOCK_MAX_HISTORY_DAYS=60``
    # through its normal ``lax`` integer coercion. A ``before`` validator
    # rejects ``bool`` (``True``/``False`` are ``int`` subclasses) and
    # any ``float``/fractional-string form so a misconfigured consumer
    # cannot silently bind ``enabled=True`` or ``1.0`` to this field;
    # the ``model_post_init`` guard below still rejects ``<= 0`` so the
    # ``WINDOW_OUT_OF_RANGE`` semantics stay meaningful.
    max_history_days: int = _DEFAULT_MAX_HISTORY_DAYS

    @field_validator("max_history_days", mode="before")
    @classmethod
    def _coerce_max_history_days(cls, value: object) -> object:
        if isinstance(value, bool):
            raise TypeError(
                "BaostockSettings.max_history_days must be an integer, "
                f"got bool {value!r}; a misconfigured ``enabled=True`` "
                "boolean must not silently bind to max_history_days"
            )
        if isinstance(value, float):
            raise TypeError(
                "BaostockSettings.max_history_days must be an integer, "
                f"got float {value!r} (no silent truncation); the "
                "WINDOW_OUT_OF_RANGE window is measured in whole days"
            )
        if isinstance(value, str) and ("." in value or "e" in value or "E" in value):
            raise TypeError(
                "BaostockSettings.max_history_days must be an integer, "
                f"got fractional string {value!r} (no silent truncation)"
            )
        return value

    def model_post_init(self, __context: object) -> None:
        if self.adjustflag != _ADJUSTFLAG_NONE:
            raise ValueError(
                "BaostockSettings.adjustflag must be '3' (the BaoStock "
                "'no adjustment' literal); ADR-0005 §4 forbids any "
                f"non-NONE adjustment reaching the production pipeline. "
                f"got {self.adjustflag!r}"
            )
        if self.max_history_days <= 0:
            raise ValueError(
                "BaostockSettings.max_history_days must be a positive integer "
                f"(got {self.max_history_days!r}); the WINDOW_OUT_OF_RANGE "
                "guard rejects requests older than this many days "
                "before the injected clock"
            )


__all__ = ["BaostockSettings"]