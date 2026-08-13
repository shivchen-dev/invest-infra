"""Command and outcome dataclasses for the stock daily bars pipeline engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any
from uuid import UUID

from invest_domain.pipeline import PipelineRunStatus

__all__ = [
    "StockDailyBarsCommand",
    "StockDailyBarsOutcome",
]

_ERROR_SECRET_MARKERS: tuple[str, ...] = (
    "api_key",
    "access_token",
    "token=",
    "password",
    "secret",
)


def _canonicalize_status(value: Any) -> PipelineRunStatus:
    if isinstance(value, PipelineRunStatus):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise ValueError("status must be a non-empty string or PipelineRunStatus")
        try:
            return PipelineRunStatus(candidate)
        except ValueError:
            pass
        try:
            return PipelineRunStatus[candidate.upper()]
        except KeyError:
            raise ValueError(f"invalid PipelineRunStatus: {value!r}") from None
    raise TypeError(
        f"status must be PipelineRunStatus or str, got {type(value).__name__}"
    )


def _freeze_config(
    value: Mapping[str, Any] | None,
) -> MappingProxyType | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(
            f"config_snapshot must be a Mapping, got {type(value).__name__}"
        )
    materialized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                f"config_snapshot keys must be str, got {type(key).__name__}"
            )
        materialized[key] = item
    return MappingProxyType(materialized)


def _ensure_uuid_or_none(name: str, value: Any) -> None:
    if value is None or isinstance(value, UUID):
        return
    raise TypeError(f"{name} must be UUID or None, got {type(value).__name__}")


def _ensure_non_negative_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


@dataclass(frozen=True, slots=True)
class StockDailyBarsCommand:
    trade_date: date
    trigger_type: str = "dagster"
    run_id: UUID | None = None
    config_snapshot: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trade_date, date):
            raise TypeError(
                f"trade_date must be date, got {type(self.trade_date).__name__}"
            )
        if not isinstance(self.trigger_type, str):
            raise TypeError(
                f"trigger_type must be str, got {type(self.trigger_type).__name__}"
            )
        if not self.trigger_type.strip():
            raise ValueError("trigger_type must be a non-blank string")
        _ensure_uuid_or_none("run_id", self.run_id)

        frozen = _freeze_config(self.config_snapshot)
        if frozen is not self.config_snapshot:
            object.__setattr__(self, "config_snapshot", frozen)


@dataclass(frozen=True, slots=True)
class StockDailyBarsOutcome:
    status: PipelineRunStatus | str
    provider_key: str | None = None
    request_id: UUID | None = None
    attempt_id: UUID | None = None
    batch_id: UUID | None = None
    record_count: int = 0
    inserted: int = 0
    skipped: int = 0
    fallback_used: bool = False
    error_summary: str | None = None

    def __post_init__(self) -> None:
        canonical = _canonicalize_status(self.status)
        if canonical is not self.status:
            object.__setattr__(self, "status", canonical)

        if self.provider_key is not None and not isinstance(self.provider_key, str):
            raise TypeError(
                f"provider_key must be str or None, got "
                f"{type(self.provider_key).__name__}"
            )
        if self.provider_key is not None and not self.provider_key.strip():
            raise ValueError("provider_key must be a non-blank string when provided")

        _ensure_uuid_or_none("request_id", self.request_id)
        _ensure_uuid_or_none("attempt_id", self.attempt_id)
        _ensure_uuid_or_none("batch_id", self.batch_id)

        _ensure_non_negative_int("record_count", self.record_count)
        _ensure_non_negative_int("inserted", self.inserted)
        _ensure_non_negative_int("skipped", self.skipped)

        if not isinstance(self.fallback_used, bool):
            raise TypeError(
                f"fallback_used must be bool, got {type(self.fallback_used).__name__}"
            )

        if self.error_summary is not None:
            if not isinstance(self.error_summary, str):
                raise TypeError(
                    f"error_summary must be str or None, got "
                    f"{type(self.error_summary).__name__}"
                )
            if canonical not in (
                PipelineRunStatus.FAILED,
                PipelineRunStatus.PARTIAL,
            ):
                raise ValueError(
                    f"error_summary is only permitted for FAILED or PARTIAL "
                    f"status, got {canonical!r}"
                )
            lowered = self.error_summary.casefold()
            for marker in _ERROR_SECRET_MARKERS:
                if marker in lowered:
                    raise ValueError(
                        "error_summary contains a forbidden sensitive marker"
                    )
