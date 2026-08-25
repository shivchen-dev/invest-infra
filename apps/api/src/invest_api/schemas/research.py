from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from invest_domain.integration import ExternalArtifact, ExternalEvidenceItem, ExternalObservation
from invest_domain.research import EvidencePack, ResearchCase
from invest_domain.research.research_run import ResearchResult, ResearchRun
from pydantic import BaseModel, Field, model_validator


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


class ResearchCaseWorkspaceArtifactResponse(BaseModel):
    """Safe provenance summary of a bound ``ExternalArtifact``.

    The Stage 4D Task 3.3 workspace surfaces only the explicitly safe
    artifact fields — ``logical_uri``, ``content_hash``,
    ``media_type``, ``size_bytes``, ``run_id`` and ``created_at``.
    Host paths and shared-directory paths are never projected onto
    this response so the front-end cannot display them.
    """

    logical_uri: str
    content_hash: str
    media_type: str
    size_bytes: int = Field(ge=0)
    run_id: UUID
    created_at: datetime

    @classmethod
    def from_domain(
        cls, artifact: ExternalArtifact
    ) -> ResearchCaseWorkspaceArtifactResponse:
        return cls(
            logical_uri=artifact.logical_uri,
            content_hash=artifact.content_hash,
            media_type=artifact.media_type,
            size_bytes=int(artifact.size_bytes),
            run_id=artifact.run_id,
            created_at=artifact.created_at,
        )


class ResearchCaseWorkspaceDiscoveryResponse(BaseModel):
    """One external-evidence item projected onto the workspace page.

    The shape composes the admitted ``ExternalEvidenceItem`` (already
    bound to the case) with the source ``ExternalObservation`` so the
    front-end can render the WorkBuddy observation, the formal
    admission decision and the bound artifact as a single traceable
    chain.

    Field invariants:

    - ``evidence_id`` is the canonical
      ``"ext-evi:{observation_id}:{hash_prefix}"`` identifier
      computed in :class:`invest_domain.integration.ExternalEvidenceItem`.
    - ``producer`` and ``source_uri`` come from the source observation
      so the WorkBuddy observation is visibly distinct from the
      formal admission metadata in the UI.
    - ``admission_status`` carries the upstream
      :class:`invest_domain.integration.AdmissionStatus` string so
      the UI can render pending / corroborated / admitted / rejected
      / conflict states.
    - ``admission`` is the verbatim admission decision metadata the
      pipeline stored at link time (rules version, decided_by,
      checks, reason); the front-end reads but does not mutate it.
    - ``artifact`` is the safe artifact summary, or ``null`` when
      the observation has no bound artifact or the bounded lookup
      misses in storage; the workspace never fabricates artifact
      data.
    """

    evidence_id: str
    observation_id: UUID
    run_id: UUID
    producer: str
    as_of: date
    observed_at: datetime
    source_uri: str
    content_hash: str
    admission_status: str
    admission: dict[str, Any]
    artifact: ResearchCaseWorkspaceArtifactResponse | None

    @classmethod
    def from_evidence_and_observation(
        cls,
        *,
        item: ExternalEvidenceItem,
        observation: ExternalObservation,
        artifact: ExternalArtifact | None,
    ) -> ResearchCaseWorkspaceDiscoveryResponse:
        return cls(
            evidence_id=item.evidence_id,
            observation_id=item.observation_id,
            run_id=item.run_id,
            producer=observation.producer,
            as_of=observation.as_of,
            observed_at=observation.observed_at,
            source_uri=observation.source_uri,
            content_hash=item.content_hash,
            admission_status=observation.admission_status.value,
            admission=dict(item.admission),
            artifact=(
                ResearchCaseWorkspaceArtifactResponse.from_domain(artifact)
                if artifact is not None
                else None
            ),
        )


ResearchCaseWorkspaceTimelineEventType = Literal[
    "case_created",
    "evidence_pack_available",
    "external_observation",
    "research_run_started",
    "research_run_finished",
    "research_result_published",
]
"""Closed vocabulary for :class:`ResearchCaseWorkspaceTimelineItem.event_type`.

The timeline is derived strictly from existing
:class:`ResearchCaseResponse` / :class:`EvidencePackResponse` /
:class:`ResearchRunResponse` / :class:`ResearchResultResponse` /
:class:`ResearchCaseWorkspaceDiscoveryResponse` fields; the literal
exhaustively enumerates the events the derivation may emit so the
front-end can switch on ``event_type`` without an unknown branch.
"""


class ResearchCaseWorkspaceTimelineItem(BaseModel):
    """One read-only timeline event projected onto the workspace page.

    The timeline is a bounded, deterministic projection of the
    workspace's already-composed resource surfaces (case, evidence
    packs, runs / results, external discovery) so the front-end can
    render the case lifecycle as a single list without re-fanning-out
    to the resource-level endpoints. Every field is safe by
    construction:

    - ``event_type`` is one of the closed
      :data:`ResearchCaseWorkspaceTimelineEventType` literals; the
      derivation never invents a new vocabulary.
    - ``occurred_at`` carries the source timestamp when one exists in
      the domain (``case.created_at``, ``run.started_at`` /
      ``run.finished_at``, ``discovery.observed_at``,
      ``result.created_at``). It is ``None`` for
      ``evidence_pack_available`` because :class:`EvidencePack`
      exposes no creation timestamp; the workspace surfaces the
      explicit ``None`` rather than fabricating one so the
      front-end can render an ``unknown`` slot rather than a
      misleading date.
    - ``source_id`` is the canonical identifier of the row the event
      describes (``case_id`` / ``pack_id`` / ``evidence_id`` /
      ``run_id`` / ``result_id``), serialised as a string so the
      front-end can deep-link without a separate UUID parse.
    - ``status`` echoes the upstream status enum string (case status,
      data quality, admission status, run status) so the front-end
      can colour the timeline without a follow-up lookup. ``None``
      when the source row has no status to project.
    - ``label`` is a short, deterministic summary the front-end can
      render verbatim: producer / source for
      ``external_observation``, an explicit
      ``creation timestamp unavailable`` note for
      ``evidence_pack_available``, and a bounded phrase for the
      remaining events. Host paths, prompts and raw payloads never
      appear in the label.
    """

    event_type: ResearchCaseWorkspaceTimelineEventType
    occurred_at: datetime | None = None
    source_id: str
    status: str | None = None
    label: str


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
    - ``external_discovery`` is the Stage 4D Task 3.3 addition: a
      list of :class:`ResearchCaseWorkspaceDiscoveryResponse` items
      derived from the case-scoped admitted external-evidence rows.
      It is **always present** (``[]`` rather than omitted when the
      case has no bound external evidence) so the workspace page can
      render an explicit empty external-discovery slot. Items whose
      source observation was deleted in storage are skipped rather
      than emitted with a dangling observation; missing artifacts are
      projected as ``null`` so the workspace exposes an explicit
      ``artifact unavailable`` state rather than fabricating data.
    - ``timeline`` is a deterministic, sorted projection of the
      other fields, derived inside this Pydantic model by
      :meth:`_derive_timeline` (a ``model_validator(mode="after")``)
      so the application services, routers and storage layer stay
      unchanged. Events are sorted ascending by ``occurred_at``,
      with ``None`` timestamps last; ties break on ``event_type``
      then ``source_id``. The derivation never fabricates
      timestamps: ``evidence_pack_available`` events always carry
      ``occurred_at = None`` because :class:`EvidencePack` exposes
      no creation timestamp, and the label makes that explicit.

    The endpoint is read-only and never invents data: when a run has
    no published result the workspace exposes a ``null`` slot rather
    than fabricating one, and the corresponding
    ``research_result_published`` event is simply absent from the
    timeline.
    """

    case: ResearchCaseResponse
    evidence_packs: list[EvidencePackResponse] = Field(default_factory=list)
    runs: list[ResearchRunResponse] = Field(default_factory=list)
    results: list[ResearchResultResponse | None] = Field(default_factory=list)
    external_discovery: list[ResearchCaseWorkspaceDiscoveryResponse] = Field(
        default_factory=list
    )
    timeline: list[ResearchCaseWorkspaceTimelineItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_timeline(self) -> Self:
        """Populate :attr:`timeline` from the composed resource fields.

        The derivation is deterministic and bounded by the existing
        composition: the router already collects the case, evidence
        packs, runs / results and external discovery for the
        resource-level surfaces, and the timeline re-projects those
        rows onto the closed :data:`ResearchCaseWorkspaceTimelineEventType`
        vocabulary.

        Sort order: timestamped events ascending by ``occurred_at``,
        then by ``event_type`` (lexicographic), then by ``source_id``.
        Events with ``occurred_at is None`` (``evidence_pack_available``
        today) sort after every timestamped event so the
        front-end can render them as an ``unknown`` group at the
        tail of the list. No timestamp is fabricated: the
        ``evidence_pack_available`` event always carries
        ``occurred_at = None`` because :class:`EvidencePack`
        exposes no creation timestamp.
        """

        items: list[ResearchCaseWorkspaceTimelineItem] = []

        items.append(
            ResearchCaseWorkspaceTimelineItem(
                event_type="case_created",
                occurred_at=self.case.created_at,
                source_id=str(self.case.case_id),
                status=self.case.status,
                label=f"Research case created ({self.case.status})",
            )
        )

        for pack in self.evidence_packs:
            items.append(
                ResearchCaseWorkspaceTimelineItem(
                    event_type="evidence_pack_available",
                    occurred_at=None,
                    source_id=str(pack.pack_id),
                    status=pack.data_quality.quality_status,
                    label="Evidence pack available (creation timestamp unavailable)",
                )
            )

        for discovery in self.external_discovery:
            items.append(
                ResearchCaseWorkspaceTimelineItem(
                    event_type="external_observation",
                    occurred_at=discovery.observed_at,
                    source_id=discovery.evidence_id,
                    status=discovery.admission_status,
                    label=f"{discovery.producer} / {discovery.source_uri}",
                )
            )

        for run, result in zip(self.runs, self.results, strict=True):
            if run.started_at is not None:
                items.append(
                    ResearchCaseWorkspaceTimelineItem(
                        event_type="research_run_started",
                        occurred_at=run.started_at,
                        source_id=str(run.run_id),
                        status=run.status,
                        label="Research run started",
                    )
                )
            if run.finished_at is not None:
                items.append(
                    ResearchCaseWorkspaceTimelineItem(
                        event_type="research_run_finished",
                        occurred_at=run.finished_at,
                        source_id=str(run.run_id),
                        status=run.status,
                        label="Research run finished",
                    )
                )
            if result is not None:
                items.append(
                    ResearchCaseWorkspaceTimelineItem(
                        event_type="research_result_published",
                        occurred_at=result.created_at,
                        source_id=str(result.result_id),
                        status=run.status,
                        label="Research result published",
                    )
                )

        items.sort(
            key=lambda item: (
                item.occurred_at is None,
                item.occurred_at,
                item.event_type,
                item.source_id,
            )
        )

        self.timeline = items
        return self


__all__ = [
    "EvidencePackResponse",
    "ResearchCaseListResponse",
    "ResearchCaseResponse",
    "ResearchCaseWorkspaceArtifactResponse",
    "ResearchCaseWorkspaceDiscoveryResponse",
    "ResearchCaseWorkspaceResponse",
    "ResearchCaseWorkspaceTimelineEventType",
    "ResearchCaseWorkspaceTimelineItem",
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
