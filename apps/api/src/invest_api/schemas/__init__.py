"""Pydantic response schemas used by the FastAPI routers.

Re-exports the legacy cross-cutting shapes from
:mod:`invest_api.schemas.common` so that ``from invest_api.schemas
import HealthResponse`` keeps working for the pre-PR-09 endpoints, and
surfaces the PR-09 ETF and candidate-pool schemas as namespace
modules.
"""

from __future__ import annotations

from invest_api.schemas.candidate_pool import (
    CandidatePoolDiffResponse,
    CandidatePoolItemResponse,
    CandidatePoolLatestResponse,
    ExclusionReasonResponse,
    RuleOutcomeResponse,
)
from invest_api.schemas.common import (
    HealthResponse,
)
from invest_api.schemas.common import (
    InstrumentListResponse as LegacyInstrumentListResponse,
)
from invest_api.schemas.common import (
    InstrumentResponse as LegacyInstrumentResponse,
)
from invest_api.schemas.data_freshness import DataFreshnessResponse, DataFreshnessStatus
from invest_api.schemas.etf import (
    DailyBarListResponse,
    DailyBarResponse,
    InstrumentListResponse,
    InstrumentResponse,
)
from invest_api.schemas.pipeline_runs import PipelineRunListResponse, PipelineRunResponse
from invest_api.schemas.research import (
    EvidencePackResponse,
    ResearchCaseListResponse,
    ResearchCaseResponse,
    ResearchResultResponse,
    ResearchRunListResponse,
    ResearchRunResponse,
)

__all__ = [
    "CandidatePoolDiffResponse",
    "CandidatePoolItemResponse",
    "CandidatePoolLatestResponse",
    "DailyBarListResponse",
    "DailyBarResponse",
    "DataFreshnessResponse",
    "DataFreshnessStatus",
    "ExclusionReasonResponse",
    "EvidencePackResponse",
    "HealthResponse",
    "InstrumentListResponse",
    "InstrumentResponse",
    "LegacyInstrumentListResponse",
    "LegacyInstrumentResponse",
    "PipelineRunResponse",
    "PipelineRunListResponse",
    "ResearchCaseListResponse",
    "ResearchCaseResponse",
    "ResearchResultResponse",
    "ResearchRunListResponse",
    "ResearchRunResponse",
    "RuleOutcomeResponse",
]
