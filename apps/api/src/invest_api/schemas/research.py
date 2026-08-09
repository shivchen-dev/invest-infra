from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase
from invest_domain.research.research_run import ResearchResult, ResearchRun
from pydantic import BaseModel, Field


class ResearchCaseResponse(BaseModel):
    case_id: UUID
    instrument_id: UUID
    as_of_date: date
    question: str
    horizon: str
    status: str
    created_at: datetime
    closed_at: datetime | None = None
    candidate_pool_run_id: UUID | None = None

    @classmethod
    def from_domain(cls, case: ResearchCase) -> ResearchCaseResponse:
        return cls(
            case_id=case.case_id,
            instrument_id=case.instrument_id.value,
            as_of_date=case.as_of_date,
            question=case.question,
            horizon=case.horizon,
            status=case.status.value,
            created_at=case.created_at,
            closed_at=case.closed_at,
            candidate_pool_run_id=case.candidate_pool_run_id,
        )


class ResearchCaseListResponse(BaseModel):
    items: list[ResearchCaseResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class EvidenceCaseResponse(BaseModel):
    case_id: UUID | None = None
    instrument_id: UUID
    as_of_date: date
    question: str
    horizon: str


class EvidenceInstrumentResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    name: str
    exchange: str
    currency: str


class EvidenceMarketSnapshotResponse(BaseModel):
    latest_trade_date: date | None
    latest_close: Decimal | None
    currency: str
    observed_trading_days: int
    valid_price_days: int
    suspended_days: int


class EvidenceFactorResponse(BaseModel):
    factor_key: str
    value: Decimal | None
    unit: str = Field(
        description=(
            "Measurement unit supplied by the frozen factor contract; interpret value "
            "using this field without percentage or currency rescaling."
        )
    )
    window: int
    observed_date: date
    quality_status: str
    source_kind: str
    source_ref: str
    evidence_id: str | None


class EvidenceDataQualityResponse(BaseModel):
    freshness_status: str
    quality_status: str
    target_trading_days: int
    observed_trading_days: int
    valid_price_days: int
    invalid_days: int
    suspended_days: int
    conflict_detected: bool


class EvidenceSourceReferenceResponse(BaseModel):
    source_kind: str
    source_ref: str
    observed_date: date
    quality_status: str
    revision: int | None


class EvidencePackResponse(BaseModel):
    pack_id: UUID | None
    case: EvidenceCaseResponse
    instrument: EvidenceInstrumentResponse
    market_snapshot: EvidenceMarketSnapshotResponse
    factors: list[EvidenceFactorResponse]
    data_quality: EvidenceDataQualityResponse
    missing_fields: list[str]
    warnings: list[str]
    source_refs: list[EvidenceSourceReferenceResponse]
    schema_version: str
    factor_set_key: str
    factor_set_version: str
    pack_hash: str
    generated_at: datetime | None

    @classmethod
    def from_domain(cls, pack: EvidencePack) -> EvidencePackResponse:
        return cls(
            pack_id=pack.pack_id,
            case=EvidenceCaseResponse(
                case_id=UUID(str(pack.case.case_id)) if pack.case.case_id else None,
                instrument_id=pack.case.instrument_id.value,
                as_of_date=pack.case.as_of_date,
                question=pack.case.question,
                horizon=pack.case.horizon,
            ),
            instrument=EvidenceInstrumentResponse(
                instrument_id=pack.instrument.instrument_id.value,
                symbol=pack.instrument.symbol,
                name=pack.instrument.name,
                exchange=pack.instrument.exchange,
                currency=pack.instrument.currency,
            ),
            market_snapshot=EvidenceMarketSnapshotResponse.model_validate(
                pack.market_snapshot, from_attributes=True
            ),
            factors=[
                EvidenceFactorResponse.model_validate(item, from_attributes=True)
                for item in pack.factors
            ],
            data_quality=EvidenceDataQualityResponse.model_validate(
                pack.data_quality, from_attributes=True
            ),
            missing_fields=list(pack.missing_fields),
            warnings=list(pack.warnings),
            source_refs=[
                EvidenceSourceReferenceResponse.model_validate(item, from_attributes=True)
                for item in pack.source_refs
            ],
            schema_version=pack.schema_version,
            factor_set_key=pack.factor_set.key,
            factor_set_version=pack.factor_set.version,
            pack_hash=pack.pack_hash,
            generated_at=pack.generated_at,
        )


class ResearchRunResponse(BaseModel):
    run_id: UUID
    case_id: UUID
    evidence_pack_id: UUID
    runner_key: str
    playbook_key: str
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None

    @classmethod
    def from_domain(cls, run: ResearchRun) -> ResearchRunResponse:
        return cls.model_validate(run, from_attributes=True)


class ResearchRunListResponse(BaseModel):
    items: list[ResearchRunResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ResearchResultResponse(BaseModel):
    result_id: UUID
    run_id: UUID
    evidence_pack_id: UUID
    conclusion: str
    risks: list[str]
    evidence_ids: list[str]
    report_markdown: str
    model_key: str
    model_version: str
    playbook_version: str
    adapter_version: str
    created_at: datetime

    @classmethod
    def from_domain(cls, result: ResearchResult) -> ResearchResultResponse:
        return cls(
            result_id=result.result_id,
            run_id=result.run_id,
            evidence_pack_id=result.evidence_pack_id,
            conclusion=result.conclusion,
            risks=list(result.risks),
            evidence_ids=list(result.evidence_ids),
            report_markdown=result.report_markdown,
            model_key=result.model_key,
            model_version=result.model_version,
            playbook_version=result.playbook_version,
            adapter_version=result.adapter_version,
            created_at=result.created_at,
        )


ResearchDashboardDataQuality = Literal["empty", "partial", "complete"]
"""Coarse vocabulary for the dashboard ``data_quality`` field.

Derived strictly from existing storage state:

- ``"empty"`` — no ``ResearchCase`` rows exist at all.
- ``"partial"`` — at least one case exists but the most recent one is
  not yet bound to any ``EvidencePack`` (the evidence pipeline has not
  finished for the latest case).
- ``"complete"`` — the most recent case has at least one bound
  ``EvidencePack``. The dashboard never inspects factor quality
  itself; the Evidence Status sub-envelope carries the
  ``quality_status`` / ``freshness_status`` for the single bound pack.
"""


ResearchDashboardFreshness = Literal["unknown", "current", "stale"]
"""Coarse vocabulary for the dashboard ``freshness`` field.

Derived strictly from the latest ``ResearchCase.as_of_date`` versus the
market clock's latest weekday (see :mod:`invest_api.clock`):

- ``"unknown"`` — no cases exist; no claim is made about freshness.
- ``"current"`` — the latest case's ``as_of_date`` matches the latest
  weekday the market clock has resolved to.
- ``"stale"`` — the latest case's ``as_of_date`` predates the latest
  weekday.
"""


class ResearchDashboardMarketStatus(BaseModel):
    """Explicit empty state for the dashboard's ``market_status`` slot.

    The PR-W03 dashboard deliberately does **not** invent market /
    factor values. No market dashboard source is registered yet, so
    the only legal response is ``state = "unavailable"`` with a
    machine-readable ``reason`` so downstream consumers can render a
    stable empty placeholder rather than fabricating numbers.
    """

    state: Literal["unavailable"]
    reason: str = Field(
        description=(
            "Stable identifier explaining why the market dashboard "
            "slot is empty. The PR-W03 dashboard never invents market "
            "values, so the only legal reason is that no market "
            "dashboard source is registered."
        )
    )


class ResearchDashboardEvidenceStatus(BaseModel):
    """Explicit empty / available state for the latest-case evidence slot.

    The dashboard always reports one of two states:

    - ``"empty"`` — no cases exist, or the latest case exists but has
      no bound ``EvidencePack`` rows. ``case_id`` echoes the case
      being reported (when available) so the front-end can deep-link
      to it; ``pack_id`` is ``None``.
    - ``"available"`` — the latest case has at least one bound pack
      and the surface carries the pack-level identifiers and quality
      metadata. Only the **first** bound pack is summarised; the full
      pack list is intentionally not enumerated on the dashboard.
    """

    state: Literal["empty", "available"]
    case_id: UUID | None = None
    pack_id: UUID | None = None
    schema_version: str | None = None
    factor_set_key: str | None = None
    factor_set_version: str | None = None
    quality_status: str | None = None
    freshness_status: str | None = None


class ResearchDashboardResearchSummary(BaseModel):
    """Deterministic counts and the latest case for the dashboard.

    ``case_count`` / ``run_count`` are derived from the storage
    readers' ``count_all`` so the values are exact, not bounded by the
    ``recent_runs`` cap. ``latest_case`` is the first row of the
    case reader's deterministic ``created_at`` descending ordering,
    or ``None`` when no cases exist; the dashboard never reaches into
    a different ordering or derives a "best" case heuristically.
    """

    case_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    latest_case: ResearchCaseResponse | None = None


class ResearchDashboardResponse(BaseModel):
    """Response envelope for the ``GET /api/v1/research-dashboard`` endpoint.

    The dashboard is a read-only aggregate over the existing PR-7
    resource-level endpoints so the front-end can render the cockpit
    first screen with a single round trip. Every field is derived
    strictly from existing :class:`ResearchCase` /
    :class:`ResearchRun` / :class:`EvidencePack` storage state; no
    market / factor values or investment conclusions are invented on
    this path.

    - ``schema_version`` is the response contract version (currently
      ``"1.0.0"``); it is independent of the evidence-pack schema
      version reported under ``evidence_status``.
    - ``generated_at`` is the UTC wall-clock stamp the router applies
      when it builds the response (two callers hitting the service in
      the same instant observe different timestamps).
    - ``as_of_date`` echoes the latest ``ResearchCase.as_of_date`` so
      the front-end can label the dashboard without a follow-up
      round trip; ``None`` when no cases exist.
    - ``data_quality`` and ``freshness`` use the coarse PR-W03
      vocabularies documented on :data:`ResearchDashboardDataQuality`
      and :data:`ResearchDashboardFreshness`.
    - ``market_status`` is always the explicit
      ``{"state": "unavailable", "reason": "..."}`` shape until a
      market dashboard source is registered.
    - ``evidence_status`` distinguishes the empty case from the
      available case; when ``available`` the surface carries the pack
      identifiers and the existing ``QualityStatus`` /
      ``FreshnessStatus`` enum strings.
    - ``recent_runs`` is a bounded page (the same shape
      :class:`ResearchRunResponse` already used by
      ``/api/v1/research-runs``) so consumers can compose the
      dashboard timeline widget without fanning out to the
      resource-level endpoint.
    """

    schema_version: str
    generated_at: datetime
    as_of_date: date | None = None
    data_quality: ResearchDashboardDataQuality
    freshness: ResearchDashboardFreshness
    market_status: ResearchDashboardMarketStatus
    research_summary: ResearchDashboardResearchSummary
    evidence_status: ResearchDashboardEvidenceStatus
    recent_runs: list[ResearchRunResponse] = Field(default_factory=list)


class ResearchCaseWorkspaceResponse(BaseModel):
    """Composite read-only envelope for the Research Case workspace page.

    Composes the existing resource shapes so the front-end can render
    the case, its bound evidence packs, the runs attached to the case
    and the (nullable) result for each run in a single round trip. The
    endpoint is the PR-W05 first increment; only the API/backend
    contract is shipped here.

    Field invariants:

    - ``case`` always echoes the canonical case detail shape used by
      ``GET /api/v1/research-cases/{case_id}``; the router enforces
      the ``case_id`` URL parameter matches the resource.
    - ``evidence_packs`` is the same list shape as
      ``GET /api/v1/research-cases/{case_id}/evidence`` (already
      serialised by :class:`EvidencePackResponse`) but is **always
      present** - it is ``[]`` rather than omitted when the case has
      no bound pack, so the workspace page can render an explicit
      empty evidence slot.
    - ``runs`` is the same per-run shape used by
      ``GET /api/v1/research-runs/{run_id}`` and is always present
      (the storage repository returns ``[]`` rather than ``None``
      when the case has no runs).
    - ``results`` is **parallel to** ``runs``: ``results[i]``
      corresponds to ``runs[i]``; ``results[i] is None`` when the run
      has not (yet) produced a result. The pair is never reordered
      server-side so the front-end can rely on positional pairing.
      The list always carries exactly one entry per run, never an
      arbitrary subset.

    The endpoint is read-only and never invents data: when a run has
    no published result the workspace exposes a ``null`` slot rather
    than fabricating one.
    """

    case: ResearchCaseResponse
    evidence_packs: list[EvidencePackResponse] = Field(default_factory=list)
    runs: list[ResearchRunResponse] = Field(default_factory=list)
    results: list[ResearchResultResponse | None] = Field(default_factory=list)


__all__ = [
    "EvidencePackResponse",
    "ResearchCaseListResponse",
    "ResearchCaseResponse",
    "ResearchCaseWorkspaceResponse",
    "ResearchDashboardDataQuality",
    "ResearchDashboardEvidenceStatus",
    "ResearchDashboardFreshness",
    "ResearchDashboardMarketStatus",
    "ResearchDashboardResearchSummary",
    "ResearchDashboardResponse",
    "ResearchResultResponse",
    "ResearchRunListResponse",
    "ResearchRunResponse",
]
