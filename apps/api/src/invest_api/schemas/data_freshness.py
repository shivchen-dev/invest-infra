"""Pydantic response schemas for the ``/api/v1/data-freshness`` read-only endpoint.

The endpoint reports a coarse health summary of the personal-ETF daily
pipeline so the front-end can show "data is fresh / stale / missing /
partial / failed" without composing five separate API calls. The
response shape is deliberately flat and uses the same vocabulary as the
storage layer (``published``, ``partial``, ``failed``) so the front-end
can map status strings 1:1 to UI badges.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DataFreshnessStatus = Literal["fresh", "partial", "stale", "missing", "failed"]


class DataFreshnessResponse(BaseModel):
    """Response envelope for the ``GET /api/v1/data-freshness`` endpoint.

    ``status`` follows the same vocabulary the front-end uses for the
    personal daily-job banner. ``missing_count`` is the gap between the
    active instrument universe and the daily bars observed for
    ``expected_trade_date``; it is always
    ``max(0, universe_count - daily_bar_count)`` regardless of the
    high-level ``status`` so the UI can surface a progress bar.
    """

    as_of: datetime
    latest_published_trade_date: date | None = None
    universe_count: int = Field(ge=0)
    daily_bar_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    snapshot_id: UUID | None = None
    pipeline_run_id: UUID | None = None
    pipeline_status: str | None = None
    status: DataFreshnessStatus


__all__ = ["DataFreshnessResponse", "DataFreshnessStatus"]
