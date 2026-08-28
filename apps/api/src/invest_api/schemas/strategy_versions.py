"""Public Pydantic response for the active StrategyVersion endpoint (Slice 1A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from invest_api.application.strategy_versions import StrategyVersionView


class StrategyVersionResponse(BaseModel):
    schema_version: str | None
    strategy_key: str
    version: str
    active: bool
    artifact_hash: str
    strategy: dict[str, Any]
    approved_at: datetime
    activated_at: datetime

    @classmethod
    def from_view(cls, view: StrategyVersionView) -> StrategyVersionResponse:
        strategy_dict = dict(view.strategy)
        raw_schema_version = strategy_dict.get("schema_version")
        schema_version = raw_schema_version if isinstance(raw_schema_version, str) else None
        return cls(
            schema_version=schema_version,
            strategy_key=view.strategy_key,
            version=view.version,
            active=view.active,
            artifact_hash=view.artifact_hash,
            strategy=strategy_dict,
            approved_at=view.approved_at,
            activated_at=view.activated_at,
        )


__all__ = ["StrategyVersionResponse"]
