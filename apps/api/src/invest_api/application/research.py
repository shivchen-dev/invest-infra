from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase
from invest_domain.research.research_run import ResearchResult, ResearchRun
from sqlalchemy.exc import SQLAlchemyError

from invest_api import clock as market_clock
from invest_api.application.data_freshness import latest_weekday

DASHBOARD_SCHEMA_VERSION: str = "1.0.0"
"""Frozen schema version for the ``GET /api/v1/research-dashboard`` envelope.

Independent of the evidence-pack ``SCHEMA_VERSION`` so the dashboard
contract can evolve without coupling to the evidence-payload shape.
"""


DASHBOARD_MARKET_UNAVAILABLE_REASON: str = "no market dashboard source registered"
"""Stable reason string for ``market_status.state == "unavailable"``.

PR-W03 deliberately does not invent market / factor values; this
string is the only legal reason until a market dashboard source is
registered in a follow-up slice.
"""


DASHBOARD_RECENT_RUNS_LIMIT: int = 10
"""Internal bound for ``recent_runs`` on the dashboard endpoint.

Kept small and constant so the dashboard never fans out beyond the
first page of the resource-level ``/api/v1/research-runs`` list.
The bound is applied server-side; the front-end never sees a
``recent_runs`` list larger than this constant regardless of how
many runs exist in storage.
"""


ResearchDashboardDataQuality = Literal["empty", "partial", "complete"]
"""Coarse vocabulary for the dashboard ``data_quality`` field.

Re-exported here so the application service and the Pydantic schema
share a single Literal type. See
:class:`invest_api.schemas.research.ResearchDashboardResponse` for
the per-state semantics.
"""


ResearchDashboardFreshness = Literal["unknown", "current", "stale"]
"""Coarse vocabulary for the dashboard ``freshness`` field.

Re-exported here so the application service and the Pydantic schema
share a single Literal type. See
:class:`invest_api.schemas.research.ResearchDashboardResponse` for
the per-state semantics.
"""


class ResearchCaseReader(Protocol):
    def list_recent(self, *, limit: int, offset: int) -> list[ResearchCase]: ...
    def count_all(self) -> int: ...
    def get(self, case_id: UUID) -> ResearchCase | None: ...


class ResearchEvidenceReader(Protocol):
    def list_by_case(self, case_id: UUID) -> list[EvidencePack]: ...


class ResearchRunReader(Protocol):
    def list_recent(self, *, limit: int, offset: int) -> list[ResearchRun]: ...
    def count_all(self) -> int: ...
    def get(self, run_id: UUID) -> ResearchRun | None: ...


class ResearchResultReader(Protocol):
    def get_by_run_id(self, run_id: UUID) -> ResearchResult | None: ...


class ResearchQueryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResearchDashboardMarketStatusView:
    """Domain view backing :class:`ResearchDashboardMarketStatus`.

    The PR-W03 dashboard always reports ``state == "unavailable"``
    with the stable reason string; the dataclass is intentionally
    small so the Pydantic schema can stay trivially flat.
    """

    state: Literal["unavailable"]
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchDashboardEvidenceStatusView:
    """Domain view backing :class:`ResearchDashboardEvidenceStatus`.

    ``state == "empty"`` covers two upstream situations that the
    front-end should render identically: no cases exist at all, or
    the latest case exists but has no bound ``EvidencePack``. The
    ``case_id`` field echoes the case being reported (when
    available) so the front-end can deep-link to it from the
    dashboard even when the evidence slot is empty.
    """

    state: Literal["empty", "available"]
    case_id: UUID | None
    pack_id: UUID | None
    schema_version: str | None
    factor_set_key: str | None
    factor_set_version: str | None
    quality_status: str | None
    freshness_status: str | None


@dataclass(frozen=True, slots=True)
class ResearchDashboardResearchSummaryView:
    """Domain view backing :class:`ResearchDashboardResearchSummary`.

    Counts are exact (taken from ``count_all``) so the dashboard
    summary line is not subject to the ``recent_runs`` bound;
    ``latest_case`` is the first row of the case reader's
    deterministic ``created_at`` descending ordering, or ``None``
    when no cases exist.
    """

    case_count: int
    run_count: int
    latest_case: ResearchCase | None


@dataclass(frozen=True, slots=True)
class ResearchDashboardView:
    """Small domain view backing the dashboard response envelope.

    ``as_of_date`` is the latest case's ``as_of_date`` (or ``None``)
    and ``generated_at`` is intentionally absent — the router stamps
    it so two callers hitting the service in the same instant
    observe different response timestamps (matches the PR-02
    ``DataFreshnessView`` / ``_to_response`` convention).
    """

    schema_version: str
    as_of_date: date | None
    data_quality: ResearchDashboardDataQuality
    freshness: ResearchDashboardFreshness
    market_status: ResearchDashboardMarketStatusView
    research_summary: ResearchDashboardResearchSummaryView
    evidence_status: ResearchDashboardEvidenceStatusView
    recent_runs: list[ResearchRun]


class ResearchQueryService:
    def __init__(
        self,
        case_repository: ResearchCaseReader,
        evidence_repository: ResearchEvidenceReader,
        run_repository: ResearchRunReader,
        result_repository: ResearchResultReader,
    ) -> None:
        self._cases = case_repository
        self._evidence = evidence_repository
        self._runs = run_repository
        self._results = result_repository

    def list_cases(self, *, limit: int, offset: int) -> tuple[list[ResearchCase], int]:
        try:
            return (
                self._cases.list_recent(limit=limit, offset=offset),
                self._cases.count_all(),
            )
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_case(self, case_id: UUID) -> ResearchCase | None:
        try:
            return self._cases.get(case_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_case_evidence(self, case_id: UUID) -> list[EvidencePack] | None:
        try:
            if self._cases.get(case_id) is None:
                return None
            return self._evidence.list_by_case(case_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def list_runs(self, *, limit: int, offset: int) -> tuple[list[ResearchRun], int]:
        try:
            return (
                self._runs.list_recent(limit=limit, offset=offset),
                self._runs.count_all(),
            )
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_run(self, run_id: UUID) -> ResearchRun | None:
        try:
            return self._runs.get(run_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_run_result(self, run_id: UUID) -> ResearchResult | None:
        try:
            if self._runs.get(run_id) is None:
                return None
            return self._results.get_by_run_id(run_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_dashboard(self) -> ResearchDashboardView:
        """Return the read-only dashboard view.

        The orchestration sequence is deterministic so two callers
        hitting the service in the same instant observe the same
        logical state:

        1. ``count_all`` for both cases and runs (exact totals).
        2. ``list_recent(limit=1, offset=0)`` on cases to resolve the
           latest case; the case reader's deterministic ordering
           (``created_at`` descending) gives the canonical answer.
        3. ``list_recent(limit=DASHBOARD_RECENT_RUNS_LIMIT, offset=0)``
           on runs for the bounded ``recent_runs`` page.
        4. ``list_by_case(latest_case.case_id)`` to resolve the
           evidence slot — only when the latest case exists.
        5. Derive ``as_of_date``, ``data_quality``, ``freshness``,
           and the empty / available evidence status from the
           resolved state. ``market_status`` is the explicit
           ``unavailable`` slot for PR-W03 (no source registered).

        ``SQLAlchemyError`` from any reader call is translated to
        :class:`ResearchQueryError`; the error boundary wraps the
        whole sequence so the dashboard fails closed with the same
        sanitized 500 detail the resource-level endpoints do.
        """

        try:
            return self._build_dashboard_view()
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def _build_dashboard_view(self) -> ResearchDashboardView:
        case_count = int(self._cases.count_all())
        run_count = int(self._runs.count_all())

        latest_case: ResearchCase | None = None
        if case_count > 0:
            recent_cases = self._cases.list_recent(limit=1, offset=0)
            latest_case = recent_cases[0] if recent_cases else None

        recent_runs = self._runs.list_recent(
            limit=DASHBOARD_RECENT_RUNS_LIMIT, offset=0
        )

        evidence_status = self._build_evidence_status(latest_case)

        as_of_date = latest_case.as_of_date if latest_case is not None else None
        data_quality = _derive_data_quality(
            case_count=case_count, has_evidence_pack=evidence_status.state == "available"
        )
        freshness = _derive_freshness(latest_case)

        market_status = ResearchDashboardMarketStatusView(
            state="unavailable",
            reason=DASHBOARD_MARKET_UNAVAILABLE_REASON,
        )

        research_summary = ResearchDashboardResearchSummaryView(
            case_count=case_count,
            run_count=run_count,
            latest_case=latest_case,
        )

        return ResearchDashboardView(
            schema_version=DASHBOARD_SCHEMA_VERSION,
            as_of_date=as_of_date,
            data_quality=data_quality,
            freshness=freshness,
            market_status=market_status,
            research_summary=research_summary,
            evidence_status=evidence_status,
            recent_runs=list(recent_runs),
        )

    def _build_evidence_status(
        self, latest_case: ResearchCase | None
    ) -> ResearchDashboardEvidenceStatusView:
        if latest_case is None:
            return ResearchDashboardEvidenceStatusView(
                state="empty",
                case_id=None,
                pack_id=None,
                schema_version=None,
                factor_set_key=None,
                factor_set_version=None,
                quality_status=None,
                freshness_status=None,
            )

        packs = self._evidence.list_by_case(latest_case.case_id)
        if not packs:
            return ResearchDashboardEvidenceStatusView(
                state="empty",
                case_id=latest_case.case_id,
                pack_id=None,
                schema_version=None,
                factor_set_key=None,
                factor_set_version=None,
                quality_status=None,
                freshness_status=None,
            )

        first_pack = packs[0]
        pack_id = first_pack.pack_id
        return ResearchDashboardEvidenceStatusView(
            state="available",
            case_id=latest_case.case_id,
            pack_id=pack_id,
            schema_version=first_pack.schema_version,
            factor_set_key=first_pack.factor_set.key,
            factor_set_version=first_pack.factor_set.version,
            quality_status=first_pack.data_quality.quality_status.value,
            freshness_status=first_pack.data_quality.freshness_status.value,
        )


def _derive_data_quality(
    *, case_count: int, has_evidence_pack: bool
) -> ResearchDashboardDataQuality:
    if case_count <= 0:
        return "empty"
    if not has_evidence_pack:
        return "partial"
    return "complete"


def _derive_freshness(
    latest_case: ResearchCase | None,
) -> ResearchDashboardFreshness:
    if latest_case is None:
        return "unknown"
    expected = latest_weekday(market_clock.market_today())
    if latest_case.as_of_date >= expected:
        return "current"
    return "stale"


__all__ = [
    "DASHBOARD_MARKET_UNAVAILABLE_REASON",
    "DASHBOARD_RECENT_RUNS_LIMIT",
    "DASHBOARD_SCHEMA_VERSION",
    "ResearchCaseReader",
    "ResearchDashboardDataQuality",
    "ResearchDashboardEvidenceStatusView",
    "ResearchDashboardFreshness",
    "ResearchDashboardMarketStatusView",
    "ResearchDashboardResearchSummaryView",
    "ResearchDashboardView",
    "ResearchEvidenceReader",
    "ResearchQueryError",
    "ResearchQueryService",
    "ResearchResultReader",
    "ResearchRunReader",
]
