"""Tests for :class:`ResearchCenterQueryService`.

Bypasses the HTTP layer and the storage readers: constructs the real
:class:`ResearchCenterQueryService` against lightweight mocks of the
five upstream application services so the Slice 1 contract state
machine, observation mapping, capability placeholders, ``as_of_date``
resolution and narrow per-source error boundary can be asserted in
isolation; Slice 2A adds parallel coverage for the ``research``
sub-segment projection driven by
:meth:`ResearchQueryService.get_dashboard`; Slice 2B adds parallel
coverage for the ``candidate_pool`` and ``opportunities``
sub-segments driven by
:meth:`CandidatePoolQueryService.get_latest` and
:meth:`ExternalWorkflowQueryService.list_radar`.

Only :class:`MarketBreadthQueryError`,
:class:`DataFreshnessQueryError`, :class:`ResearchQueryError`,
:class:`CandidatePoolQueryError`,
:class:`CandidatePoolSnapshotMissingError` and a
:class:`sqlalchemy.exc.SQLAlchemyError` raised by the external
workflow reader are translated into a missing or failed sub-segment;
any other exception must propagate so the router's generic error
boundary stays in charge of sanitising driver-level detail.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from invest_api.application.candidate_pool import (
    CandidatePoolQueryError,
    CandidatePoolQueryService,
    CandidatePoolSnapshotMissingError,
    LatestCandidatePoolView,
)
from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    DataFreshnessView,
)
from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.application.market_breadth import (
    MarketBreadthQueryError,
    MarketBreadthQueryService,
)
from invest_api.application.research import (
    DASHBOARD_MARKET_UNAVAILABLE_REASON,
    DASHBOARD_SCHEMA_VERSION,
    ResearchDashboardEvidenceStatusView,
    ResearchDashboardMarketStatusView,
    ResearchDashboardResearchSummaryView,
    ResearchDashboardView,
    ResearchQueryError,
    ResearchQueryService,
)
from invest_api.application.research_center import (
    CANDIDATE_POOL_FAILED_REASON,
    CANDIDATE_POOL_SNAPSHOT_MISSING_REASON,
    OPPORTUNITY_EMPTY_REASON,
    OPPORTUNITY_FAILED_REASON,
    OPPORTUNITY_RADAR_LIMIT,
    RESEARCH_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ResearchCenterCandidatePoolSummaryView,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterLatestCaseView,
    ResearchCenterOpportunitySummaryView,
    ResearchCenterQueryService,
    ResearchCenterResearchEvidenceView,
    ResearchCenterResearchSummaryView,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_domain.integration.models import AdmissionStatus, ExternalObservation
from invest_domain.research.models import FreshnessStatus, QualityStatus
from sqlalchemy.exc import OperationalError

_DEFAULT_SNAPSHOT_INPUT_ID: UUID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_DEFAULT_AS_OF: date = date(2026, 8, 15)


def _snapshot(
    *,
    as_of_date: date = _DEFAULT_AS_OF,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    freshness_status: FreshnessStatus = FreshnessStatus.FRESH,
    algorithm_version: str = "2.0.0",
    scope_type: str = "ashare_universe",
    scope_key: str = "ashare_active_universe_v1",
    observations: tuple[MarketObservation, ...] | None = None,
) -> MarketObservationSnapshot:
    if observations is None:
        observations = (
            MarketObservation(
                observation_key="advancing_ratio",
                value=Decimal("0.60"),
                unit="ratio",
                observed_date=as_of_date,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
                quality_status=QualityStatus.COMPLETE,
            ),
        )
    return MarketObservationSnapshot(
        input_snapshot_id=_DEFAULT_SNAPSHOT_INPUT_ID,
        as_of_date=as_of_date,
        observations=observations,
        algorithm_version=algorithm_version,
        scope_type=scope_type,
        scope_key=scope_key,
        quality_status=quality_status,
        freshness_status=freshness_status,
    )


def _freshness_view(
    *,
    status: str,
    latest_published_trade_date: date | None = _DEFAULT_AS_OF,
    universe_count: int = 100,
    daily_bar_count: int = 100,
    missing_count: int = 0,
    snapshot_id: UUID | None = None,
    pipeline_run_id: UUID | None = None,
    pipeline_status: str | None = "succeeded",
    candidate_count: int = 100,
    expected_trade_date: date = _DEFAULT_AS_OF,
) -> DataFreshnessView:
    return DataFreshnessView(
        expected_trade_date=expected_trade_date,
        latest_published_trade_date=latest_published_trade_date,
        universe_count=universe_count,
        daily_bar_count=daily_bar_count,
        missing_count=missing_count,
        candidate_count=candidate_count,
        snapshot_id=snapshot_id,
        pipeline_run_id=pipeline_run_id,
        pipeline_status=pipeline_status,
        status=status,
    )


def _empty_freshness(status: str) -> DataFreshnessView:
    return _freshness_view(
        status=status,
        latest_published_trade_date=None,
        universe_count=0,
        daily_bar_count=0,
        missing_count=0,
        candidate_count=0,
        pipeline_status=("failed" if status == "failed" else None),
    )


def _latest_case_shim(*, case_id, as_of_date):
    """Return a structurally-compatible ``ResearchCase`` shim."""

    return SimpleNamespace(
        case_id=case_id,
        instrument_id=SimpleNamespace(value=uuid4()),
        as_of_date=as_of_date,
        question="Assess medium-term risks",
        horizon="20-60d",
        status=SimpleNamespace(value="draft"),
        created_at=SimpleNamespace(tzinfo=None),
        closed_at=None,
        candidate_pool_run_id=None,
    )


def _evidence_shim(
    *,
    state: str = "empty",
    case_id: UUID | None = None,
    pack_id: UUID | None = None,
    quality_status: str | None = None,
    freshness_status: str | None = None,
) -> ResearchDashboardEvidenceStatusView:
    return ResearchDashboardEvidenceStatusView(
        state=state,  # type: ignore[arg-type]
        case_id=case_id,
        pack_id=pack_id,
        schema_version="1.0.0" if pack_id is not None else None,
        factor_set_key="etf_market_state_daily" if pack_id is not None else None,
        factor_set_version="1.0.0" if pack_id is not None else None,
        quality_status=quality_status,
        freshness_status=freshness_status,
    )


def _dashboard_view(
    *,
    case_count: int,
    run_count: int,
    latest_case,
    evidence: ResearchDashboardEvidenceStatusView | None = None,
) -> ResearchDashboardView:
    if evidence is None:
        evidence = ResearchDashboardEvidenceStatusView(
            state="empty",
            case_id=None,
            pack_id=None,
            schema_version=None,
            factor_set_key=None,
            factor_set_version=None,
            quality_status=None,
            freshness_status=None,
        )
    return ResearchDashboardView(
        schema_version=DASHBOARD_SCHEMA_VERSION,
        as_of_date=latest_case.as_of_date if latest_case is not None else None,
        data_quality="complete" if case_count > 0 and evidence.state == "available" else "empty",
        freshness="unknown" if latest_case is None else "current",
        market_status=ResearchDashboardMarketStatusView(
            state="unavailable",
            reason=DASHBOARD_MARKET_UNAVAILABLE_REASON,
        ),
        research_summary=ResearchDashboardResearchSummaryView(
            case_count=case_count,
            run_count=run_count,
            latest_case=latest_case,
        ),
        evidence_status=evidence,
        recent_runs=[],
    )


_DEFAULT_RESEARCH_VIEW: ResearchDashboardView = _dashboard_view(
    case_count=0, run_count=0, latest_case=None
)


def _candidate_pool_run(
    *,
    run_id: UUID | None = None,
    trade_date: date = _DEFAULT_AS_OF,
    input_row_count: int = 3,
    included_count: int = 2,
) -> CandidatePoolRun:
    return CandidatePoolRun(
        id=run_id or uuid4(),
        trade_date=trade_date,
        algorithm_key="candidate_pool.v1",
        algorithm_version="v1.0",
        parameter_set_key="default",
        parameter_hash="a" * 64,
        input_snapshot_id=uuid4(),
        input_row_count=input_row_count,
        included_count=included_count,
        status=CandidatePoolStatus.PUBLISHED,
        created_at=datetime(2026, 7, 31, 9, tzinfo=UTC),
        published_at=datetime(2026, 7, 31, 10, tzinfo=UTC),
    )


def _candidate_pool_view(
    *,
    run: CandidatePoolRun | None = None,
) -> LatestCandidatePoolView:
    effective_run = run or _candidate_pool_run()
    snapshot = SimpleNamespace(
        id=effective_run.input_snapshot_id,
        snapshot_date=effective_run.trade_date,
        instrument_ids=[],
        content_hash="f" * 64,
        row_count=effective_run.input_row_count,
        created_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
    )
    item = SimpleNamespace(
        instrument_id=SimpleNamespace(value=uuid4()),
        included=True,
        rank=1,
        total_score=Decimal("0.85"),
    )
    return LatestCandidatePoolView(
        run=effective_run,
        snapshot=snapshot,
        items=(item,),
        instruments_by_id={},
    )


_DEFAULT_CANDIDATE_POOL_VIEW: LatestCandidatePoolView | None = _candidate_pool_view()


def _observation(
    *,
    observation_id: UUID | None = None,
    as_of: date = _DEFAULT_AS_OF,
    admission_status: AdmissionStatus = AdmissionStatus.PENDING,
) -> ExternalObservation:
    return ExternalObservation(
        observation_id=observation_id or uuid4(),
        run_id=uuid4(),
        observed_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        as_of=as_of,
        source_uri="https://example.com/observation",
        producer="fixture",
        payload={},
        admission_status=admission_status,
    )


_DEFAULT_OPPORTUNITY_OBSERVATIONS: list[ExternalObservation] = (
    _observation(admission_status=AdmissionStatus.ADMITTED),
)


def _service_with(
    *,
    breadth_return: MarketObservationSnapshot | None | Exception = None,
    freshness_return: DataFreshnessView | None | Exception = None,
    research_return: (
        ResearchDashboardView | None | Exception
    ) = _DEFAULT_RESEARCH_VIEW,
    candidate_pool_return: (
        LatestCandidatePoolView | None | Exception
    ) = _DEFAULT_CANDIDATE_POOL_VIEW,
    opportunity_return: (
        list[ExternalObservation] | None | Exception
    ) = _DEFAULT_OPPORTUNITY_OBSERVATIONS,
) -> tuple[
    ResearchCenterQueryService,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    breadth = MagicMock(
        name="MarketBreadthQueryService", spec=MarketBreadthQueryService
    )
    freshness = MagicMock(
        name="DataFreshnessQueryService", spec=DataFreshnessQueryService
    )
    research = MagicMock(
        name="ResearchQueryService", spec=ResearchQueryService
    )
    candidate_pool = MagicMock(
        name="CandidatePoolQueryService", spec=CandidatePoolQueryService
    )
    external_workflows = MagicMock(
        name="ExternalWorkflowQueryService", spec=ExternalWorkflowQueryService
    )
    if isinstance(breadth_return, Exception):
        breadth.get_latest.side_effect = breadth_return
    else:
        breadth.get_latest.return_value = breadth_return
    if isinstance(freshness_return, Exception):
        freshness.get_freshness.side_effect = freshness_return
    else:
        freshness.get_freshness.return_value = freshness_return
    if isinstance(research_return, Exception):
        research.get_dashboard.side_effect = research_return
    else:
        research.get_dashboard.return_value = research_return
    if isinstance(candidate_pool_return, Exception):
        candidate_pool.get_latest.side_effect = candidate_pool_return
    else:
        candidate_pool.get_latest.return_value = candidate_pool_return
    if isinstance(opportunity_return, Exception):
        external_workflows.list_radar.side_effect = opportunity_return
    else:
        external_workflows.list_radar.return_value = opportunity_return
    return (
        ResearchCenterQueryService(
            breadth,
            freshness,
            research,
            candidate_pool,
            external_workflows,
        ),
        breadth,
        freshness,
        research,
        candidate_pool,
        external_workflows,
    )


def test_schema_version_constant_is_frozen_at_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_research_schema_version_constant_is_frozen_at_1_0_0() -> None:
    assert RESEARCH_SCHEMA_VERSION == "1.0.0"


class TestStateDerivation:
    """Coverage for the four-state vocabulary pinned by the Slice 0 contract."""

    def test_both_fresh_and_complete_returns_available(self) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.state == "available"
        assert response.market.state == "available"

    def test_breadth_missing_with_usable_freshness_returns_partial(self) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=None,
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.state == "partial"
        assert response.market.state == "partial"
        assert response.market.breadth is None
        assert response.market.data_freshness is not None
        assert response.market.data_freshness.state == "available"

    @pytest.mark.parametrize("freshness_status", ["partial", "stale"])
    def test_freshness_degraded_status_returns_partial(
        self, freshness_status: str
    ) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(
                status=freshness_status,
                latest_published_trade_date=(
                    date(2026, 8, 14)
                    if freshness_status == "stale"
                    else _DEFAULT_AS_OF
                ),
                universe_count=100,
                daily_bar_count=80,
                missing_count=20,
            ),
        )

        response = service.get_research_center()

        assert response.state == "partial"
        assert response.market.state == "partial"
        assert response.market.data_freshness is not None
        assert response.market.data_freshness.status == freshness_status
        assert response.market.data_freshness.state == "partial"

    @pytest.mark.parametrize("error_side", ["breadth", "freshness"])
    def test_one_controlled_error_with_other_usable_returns_partial(
        self, error_side: str
    ) -> None:
        if error_side == "breadth":
            service, _, _, _, _, _ = _service_with(
                breadth_return=MarketBreadthQueryError("breadth failed"),
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _, _, _, _ = _service_with(
                breadth_return=_snapshot(),
                freshness_return=DataFreshnessQueryError("freshness failed"),
            )

        response = service.get_research_center()

        assert response.state == "partial"
        assert response.market.state == "partial"
        if error_side == "breadth":
            assert response.market.breadth is not None
            assert response.market.breadth.state == "failed"
            assert response.market.breadth.snapshot_id is None
            assert response.market.breadth.observations is None
        else:
            assert response.market.data_freshness is not None
            assert response.market.data_freshness.state == "failed"
            assert response.market.data_freshness.status == "failed"
            assert response.market.data_freshness.universe_count is None

    def test_both_sources_absent_returns_unavailable(self) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=None,
            freshness_return=_empty_freshness("missing"),
        )

        response = service.get_research_center()

        assert response.state == "unavailable"
        assert response.market.state == "unavailable"
        assert response.market.breadth is None
        assert response.market.data_freshness is not None
        assert response.market.data_freshness.status == "missing"
        assert response.market.data_freshness.state == "unavailable"

    def test_both_controlled_errors_returns_failed(self) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=MarketBreadthQueryError("breadth failed"),
            freshness_return=DataFreshnessQueryError("freshness failed"),
        )

        response = service.get_research_center()

        assert response.state == "failed"
        assert response.market.state == "failed"
        assert response.market.breadth is not None
        assert response.market.breadth.state == "failed"
        assert response.market.breadth.snapshot_id is None
        assert response.market.breadth.algorithm_version is None
        assert response.market.breadth.scope_type is None
        assert response.market.breadth.scope_key is None
        assert response.market.breadth.observations is None
        assert response.market.data_freshness is not None
        assert response.market.data_freshness.state == "failed"
        assert response.market.data_freshness.status == "failed"
        assert response.market.data_freshness.latest_published_trade_date is None
        assert response.market.data_freshness.universe_count is None
        assert response.market.data_freshness.daily_bar_count is None
        assert response.market.data_freshness.missing_count is None

    @pytest.mark.parametrize(
        ("breadth", "freshness"),
        [
            pytest.param(
                MarketBreadthQueryError("breadth failed"),
                _empty_freshness("missing"),
                id="breadth_error+freshness_missing",
            ),
            pytest.param(
                MarketBreadthQueryError("breadth failed"),
                _empty_freshness("failed"),
                id="breadth_error+freshness_failed",
            ),
            pytest.param(
                None,
                DataFreshnessQueryError("freshness failed"),
                id="breadth_missing+freshness_error",
            ),
        ],
    )
    def test_ambiguity_one_error_other_not_displayable_returns_partial(
        self,
        breadth: MarketObservationSnapshot | None | MarketBreadthQueryError,
        freshness: DataFreshnessView | DataFreshnessQueryError,
    ) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=breadth, freshness_return=freshness
        )

        response = service.get_research_center()

        assert response.state == "partial"
        assert response.market.state == "partial"


class TestUnknownExceptionPropagation:
    """Only controlled query errors are translated; anything else propagates."""

    @pytest.mark.parametrize("error_side", ["breadth", "freshness"])
    def test_unknown_exception_propagates(self, error_side: str) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        if error_side == "breadth":
            service, _, _, _, _, _ = _service_with(
                breadth_return=boom,
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _, _, _, _ = _service_with(
                breadth_return=_snapshot(),
                freshness_return=boom,
            )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestObservationMapping:
    """Breadth observations map field-by-field onto the response shape."""

    def test_maps_field_renames_preserves_value_types_and_order(self) -> None:
        observations = (
            MarketObservation(
                observation_key="above_ma60_ratio",
                value=Decimal("0.42"),
                unit="ratio",
                observed_date=_DEFAULT_AS_OF,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
            ),
            MarketObservation(
                observation_key="new_high_ratio",
                value="0.05",
                unit="ratio",
                observed_date=_DEFAULT_AS_OF,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
            ),
            MarketObservation(
                observation_key="new_low_ratio",
                value=None,
                unit="ratio",
                observed_date=_DEFAULT_AS_OF,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
            ),
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(
                observations=observations,
                algorithm_version="2.1.0",
                scope_key="ashare_active_universe_v2",
            ),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.market.breadth is not None
        view = response.market.breadth
        assert view.state == "available"
        assert view.snapshot_id.startswith("mos:")
        assert view.algorithm_version == "2.1.0"
        assert view.scope_type == "ashare_universe"
        assert view.scope_key == "ashare_active_universe_v2"
        assert [obs.key for obs in view.observations] == [
            "above_ma60_ratio",
            "new_high_ratio",
            "new_low_ratio",
        ]
        assert view.observations[0].value == Decimal("0.42")
        assert view.observations[1].value == "0.05"
        assert view.observations[2].value is None
        for observation in view.observations:
            assert observation.unit == "ratio"
            assert observation.observed_date == _DEFAULT_AS_OF
            assert observation.source_kind == "analytics"
            assert observation.source_ref == "market_breadth:2.0.0"


class TestAsOfDateResolution:
    """``as_of_date`` prefers breadth, falls back to freshness, then ``None``."""

    @pytest.mark.parametrize(
        ("breadth_as_of", "freshness_latest", "expected"),
        [
            pytest.param(
                date(2026, 8, 15),
                date(2026, 8, 14),
                date(2026, 8, 15),
                id="prefers_breadth",
            ),
            pytest.param(
                None,
                date(2026, 8, 14),
                date(2026, 8, 14),
                id="falls_back_to_freshness",
            ),
            pytest.param(
                None,
                None,
                None,
                id="none_when_neither_has_a_date",
            ),
        ],
    )
    def test_resolves_as_of_date(
        self,
        breadth_as_of: date | None,
        freshness_latest: date | None,
        expected: date | None,
    ) -> None:
        breadth_snapshot = (
            _snapshot(as_of_date=breadth_as_of) if breadth_as_of else None
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=breadth_snapshot,
            freshness_return=_freshness_view(
                status="fresh",
                latest_published_trade_date=freshness_latest,
            ),
        )

        response = service.get_research_center()

        assert response.market.as_of_date == expected


class TestCapabilityBundle:
    """The Slice 1 capability bundle is frozen until later slices land."""

    def test_capability_bundle_matches_frozen_contract(self) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.capabilities == ResearchCenterCapabilitiesView(
            opportunities=ResearchCenterCapabilityView(
                state="deferred", reason="slice_2_not_implemented"
            ),
            research=ResearchCenterCapabilityView(
                state="deferred", reason="slice_2_not_implemented"
            ),
            delivery=ResearchCenterCapabilityView(
                state="deferred", reason="slice_3_not_implemented"
            ),
            strategy=ResearchCenterCapabilityView(
                state="unavailable",
                reason="strategy_iteration_contract_not_frozen",
            ),
            discipline=ResearchCenterCapabilityView(
                state="unavailable",
                reason="position_discipline_contract_not_frozen",
            ),
        )


class TestResearchSummaryAvailable:
    """``state == "available"`` projects the dashboard verbatim."""

    def test_available_state_projects_counts_and_latest_case_identity(
        self,
    ) -> None:
        latest_case = _latest_case_shim(
            case_id=uuid4(), as_of_date=date(2026, 8, 14)
        )
        pack_id = uuid4()
        evidence = _evidence_shim(
            state="available",
            case_id=latest_case.case_id,
            pack_id=pack_id,
            quality_status="complete",
            freshness_status="fresh",
        )
        research_view = _dashboard_view(
            case_count=4,
            run_count=7,
            latest_case=latest_case,
            evidence=evidence,
        )
        service, _, _, research, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=research_view,
        )

        response = service.get_research_center()

        research_mock = response.research
        assert isinstance(
            research_mock, ResearchCenterResearchSummaryView
        )
        assert research_mock.state == "available"
        assert research_mock.case_count == 4
        assert research_mock.run_count == 7
        assert research_mock.latest_case == ResearchCenterLatestCaseView(
            case_id=latest_case.case_id,
            as_of_date=date(2026, 8, 14),
        )
        assert research_mock.evidence == ResearchCenterResearchEvidenceView(
            state="available",
            pack_id=pack_id,
            quality_status="complete",
            freshness_status="fresh",
        )
        # Source wiring: the dashboard service is invoked exactly once
        # per ``get_research_center`` call.
        research.get_dashboard.assert_called_once_with()

    def test_available_state_with_no_bound_evidence_keeps_empty_evidence_slot(
        self,
    ) -> None:
        latest_case = _latest_case_shim(
            case_id=uuid4(), as_of_date=date(2026, 8, 14)
        )
        evidence = _evidence_shim(
            state="empty",
            case_id=latest_case.case_id,
            pack_id=None,
            quality_status=None,
            freshness_status=None,
        )
        research_view = _dashboard_view(
            case_count=2,
            run_count=1,
            latest_case=latest_case,
            evidence=evidence,
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=research_view,
        )

        response = service.get_research_center()

        research_mock = response.research
        assert research_mock.state == "available"
        assert research_mock.case_count == 2
        assert research_mock.run_count == 1
        assert research_mock.latest_case is not None
        assert research_mock.latest_case.case_id == latest_case.case_id
        # Evidence slot stays empty but ``case_id`` from the dashboard
        # is not echoed in the sub-segment: the surface carries only
        # pack-level quality fields.
        assert research_mock.evidence == ResearchCenterResearchEvidenceView(
            state="empty",
            pack_id=None,
            quality_status=None,
            freshness_status=None,
        )


class TestResearchSummaryEmpty:
    """``state == "empty"`` is the explicit zero-count path."""

    def test_zero_case_count_reports_empty_state_with_observed_totals(
        self,
    ) -> None:
        research_view = _dashboard_view(
            case_count=0,
            run_count=0,
            latest_case=None,
            evidence=ResearchDashboardEvidenceStatusView(
                state="empty",
                case_id=None,
                pack_id=None,
                schema_version=None,
                factor_set_key=None,
                factor_set_version=None,
                quality_status=None,
                freshness_status=None,
            ),
        )
        service, _, _, research, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=research_view,
        )

        response = service.get_research_center()

        research_mock = response.research
        assert research_mock.state == "empty"
        # Counts are real (not fabricated ``0`` stand-ins for "no
        # data"); the dashboard reader explicitly observed zero.
        assert research_mock.case_count == 0
        assert research_mock.run_count == 0
        assert research_mock.latest_case is None
        assert research_mock.evidence == ResearchCenterResearchEvidenceView(
            state="empty",
            pack_id=None,
            quality_status=None,
            freshness_status=None,
        )
        research.get_dashboard.assert_called_once_with()

    def test_zero_case_count_with_runs_keeps_state_empty(
        self,
    ) -> None:
        # Defensive: if the dashboard ever produces zero cases but
        # positive runs (edge case in the seed data) the slice 0
        # contract still treats the latest case absence as an empty
        # research state, never as "available".
        research_view = _dashboard_view(
            case_count=0,
            run_count=3,
            latest_case=None,
            evidence=ResearchDashboardEvidenceStatusView(
                state="empty",
                case_id=None,
                pack_id=None,
                schema_version=None,
                factor_set_key=None,
                factor_set_version=None,
                quality_status=None,
                freshness_status=None,
            ),
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=research_view,
        )

        response = service.get_research_center()

        assert response.research.state == "empty"
        assert response.research.case_count == 0
        assert response.research.run_count == 3
        assert response.research.latest_case is None


class TestResearchSummaryFailure:
    """``ResearchQueryError`` is translated into the explicit ``failed`` state."""

    def test_controlled_query_error_emits_failed_with_null_counts(
        self,
    ) -> None:
        service, _, _, research, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=ResearchQueryError("connection string: postgres://user:secret@host/db"),
        )

        response = service.get_research_center()

        research_mock = response.research
        assert research_mock.state == "failed"
        # Counts are absent, not zero: zero would mean "data
        # unavailable" instead of "query failed".
        assert research_mock.case_count is None
        assert research_mock.run_count is None
        assert research_mock.latest_case is None
        assert research_mock.evidence == ResearchCenterResearchEvidenceView(
            state="empty",
            pack_id=None,
            quality_status=None,
            freshness_status=None,
        )
        research.get_dashboard.assert_called_once_with()
        # Defence-in-depth: the original exception's driver-level
        # detail never leaks into the public response field.
        assert "postgres" not in str(research_mock)
        assert "secret" not in str(research_mock)


class TestResearchSummaryDoNotAffectTopLevelState:
    """The ``research`` sub-segment must not perturb Slice 1 top-level state.

    Slice 2A only adds the sub-segment; later slices may fold it into
    the state machine. Until then, a fully-failed research read leaves
    the breadth/freshness four-state derivation untouched.
    """

    @pytest.mark.parametrize(
        "breadth_return",
        [None, MarketBreadthQueryError("boom")],
    )
    def test_failed_research_keeps_market_state_machine_intact(
        self, breadth_return
    ) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=breadth_return,
            freshness_return=_freshness_view(status="fresh"),
            research_return=ResearchQueryError("boom"),
        )

        response = service.get_research_center()

        if breadth_return is None:
            assert response.state == "partial"
            assert response.research.state == "failed"
        else:
            assert response.state == "partial"
            assert response.research.state == "failed"


class TestResearchUnknownExceptionPropagation:
    """Unknown exceptions from the research reader propagate."""

    def test_unknown_exception_propagates_through_research_path(self) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestCandidatePoolSummaryAvailable:
    """``state == "available"`` projects the published run verbatim."""

    def test_available_state_projects_run_identity_and_counts(self) -> None:
        run = _candidate_pool_run(
            run_id=uuid4(),
            trade_date=date(2026, 8, 14),
            input_row_count=10,
            included_count=4,
        )
        latest_view = _candidate_pool_view(run=run)
        service, _, _, _, candidate_pool, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=latest_view,
        )

        response = service.get_research_center()

        sub_view = response.candidate_pool
        assert isinstance(sub_view, ResearchCenterCandidatePoolSummaryView)
        assert sub_view.state == "available"
        assert sub_view.run_id == run.id
        assert sub_view.trade_date == date(2026, 8, 14)
        assert sub_view.input_row_count == 10
        assert sub_view.included_count == 4
        # Excluded count is derived from the bounded run summary;
        # we never re-read the items list to compute it.
        assert sub_view.excluded_count == 6
        assert sub_view.reason is None
        candidate_pool.get_latest.assert_called_once_with()

    def test_available_state_with_full_inclusion_has_zero_excluded(self) -> None:
        run = _candidate_pool_run(input_row_count=5, included_count=5)
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=_candidate_pool_view(run=run),
        )

        response = service.get_research_center()

        sub_view = response.candidate_pool
        assert sub_view.state == "available"
        assert sub_view.excluded_count == 0


class TestCandidatePoolSummaryEmpty:
    """``state == "empty"`` is the explicit "no published run yet" path."""

    def test_get_latest_returning_none_reports_empty_state(self) -> None:
        service, _, _, _, candidate_pool, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=None,
        )

        response = service.get_research_center()

        sub_view = response.candidate_pool
        assert sub_view.state == "empty"
        # Counts are absent, not zero: zero would mean "data
        # unavailable" instead of "no published run yet".
        assert sub_view.run_id is None
        assert sub_view.trade_date is None
        assert sub_view.input_row_count is None
        assert sub_view.included_count is None
        assert sub_view.excluded_count is None
        assert sub_view.reason is None
        candidate_pool.get_latest.assert_called_once_with()


class TestCandidatePoolSummaryFailure:
    """Controlled errors emit ``failed`` with the matching stable reason."""

    def test_query_error_emits_failed_with_candidate_pool_query_failed_reason(
        self,
    ) -> None:
        service, _, _, _, candidate_pool, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=CandidatePoolQueryError(
                "driver-level boom: postgres://user:secret@host/db"
            ),
        )

        response = service.get_research_center()

        sub_view = response.candidate_pool
        assert sub_view.state == "failed"
        assert sub_view.reason == CANDIDATE_POOL_FAILED_REASON
        # Counts are absent, not zero: zero would mean "data
        # unavailable" instead of "query failed".
        assert sub_view.run_id is None
        assert sub_view.trade_date is None
        assert sub_view.input_row_count is None
        assert sub_view.included_count is None
        assert sub_view.excluded_count is None
        candidate_pool.get_latest.assert_called_once_with()
        # Defence-in-depth: the original exception's driver-level
        # detail never leaks into the public response field.
        assert "postgres" not in str(sub_view)
        assert "secret" not in str(sub_view)

    def test_snapshot_missing_emits_failed_with_snapshot_missing_reason(
        self,
    ) -> None:
        run_id = uuid4()
        snapshot_id = uuid4()
        service, _, _, _, candidate_pool, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=CandidatePoolSnapshotMissingError(
                snapshot_id=snapshot_id, run_id=run_id
            ),
        )

        response = service.get_research_center()

        sub_view = response.candidate_pool
        assert sub_view.state == "failed"
        assert sub_view.reason == CANDIDATE_POOL_SNAPSHOT_MISSING_REASON
        # The identifier fields stay absent so the public response
        # never echoes the underlying run / snapshot identifiers.
        assert sub_view.run_id is None
        assert sub_view.trade_date is None
        assert "snapshot_id" not in str(sub_view)
        assert str(snapshot_id) not in str(sub_view)
        assert str(run_id) not in str(sub_view)
        candidate_pool.get_latest.assert_called_once_with()


class TestCandidatePoolUnknownExceptionPropagation:
    """Unknown exceptions from the candidate-pool reader propagate."""

    def test_unknown_exception_propagates_through_candidate_pool_path(
        self,
    ) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestOpportunitySummaryAvailable:
    """``state == "available"`` exposes the bounded radar slice verbatim."""

    def test_available_state_projects_count_latest_as_of_and_status_mix(
        self,
    ) -> None:
        observations = (
            _observation(
                observation_id=uuid4(),
                as_of=date(2026, 8, 14),
                admission_status=AdmissionStatus.ADMITTED,
            ),
            _observation(
                observation_id=uuid4(),
                as_of=date(2026, 8, 13),
                admission_status=AdmissionStatus.PENDING,
            ),
            _observation(
                observation_id=uuid4(),
                as_of=date(2026, 8, 12),
                admission_status=AdmissionStatus.REJECTED,
            ),
        )
        service, _, _, _, _, external_workflows = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            opportunity_return=list(observations),
        )

        response = service.get_research_center()

        sub_view = response.opportunities
        assert isinstance(sub_view, ResearchCenterOpportunitySummaryView)
        assert sub_view.state == "available"
        assert sub_view.observation_count == 3
        # ``latest_as_of`` resolves to the maximum across the bounded
        # slice, independent of the observed_at ordering.
        assert sub_view.latest_as_of == date(2026, 8, 14)
        assert sub_view.admission_status_counts == {
            "pending": 1,
            "corroborated": 0,
            "admitted": 1,
            "rejected": 1,
            "conflict": 0,
        }
        assert sub_view.reason is None
        # Source wiring: the bounded radar call is issued with the
        # frozen admission-agnostic contract arguments.
        external_workflows.list_radar.assert_called_once_with(
            status=None, limit=OPPORTUNITY_RADAR_LIMIT, offset=0
        )

    def test_admission_status_counts_use_admission_status_keys_only(
        self,
    ) -> None:
        # All observations fall into a single status: every other
        # AdmissionStatus key is still zero-defaulted so the
        # front-end never has to special-case missing keys.
        observations = [
            _observation(admission_status=AdmissionStatus.CONFLICT)
            for _ in range(2)
        ]
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            opportunity_return=observations,
        )

        response = service.get_research_center()

        sub_view = response.opportunities
        assert sub_view.state == "available"
        assert sub_view.observation_count == 2
        assert sub_view.admission_status_counts == {
            "pending": 0,
            "corroborated": 0,
            "admitted": 0,
            "rejected": 0,
            "conflict": 2,
        }


class TestOpportunitySummaryEmpty:
    """``state == "empty"`` is the explicit zero-observation path."""

    def test_list_radar_returning_empty_reports_empty_with_stable_reason(
        self,
    ) -> None:
        service, _, _, _, _, external_workflows = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            opportunity_return=[],
        )

        response = service.get_research_center()

        sub_view = response.opportunities
        assert sub_view.state == "empty"
        # Real zero is explicit: the radar reader observed zero rows.
        assert sub_view.observation_count == 0
        assert sub_view.latest_as_of is None
        assert sub_view.admission_status_counts is None
        assert sub_view.reason == OPPORTUNITY_EMPTY_REASON
        external_workflows.list_radar.assert_called_once_with(
            status=None, limit=OPPORTUNITY_RADAR_LIMIT, offset=0
        )


class TestOpportunitySummaryFailure:
    """``SQLAlchemyError`` from the radar reader is translated to ``failed``."""

    def test_sqlalchemy_error_emits_failed_with_opportunity_failed_reason(
        self,
    ) -> None:
        boom = OperationalError(
            "SELECT", {}, Exception("postgres://user:secret@host/db")
        )
        service, _, _, _, _, external_workflows = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            opportunity_return=boom,
        )

        response = service.get_research_center()

        sub_view = response.opportunities
        assert sub_view.state == "failed"
        assert sub_view.reason == OPPORTUNITY_FAILED_REASON
        # Counts are absent, not zero: zero would mean "data
        # unavailable" instead of "query failed".
        assert sub_view.observation_count is None
        assert sub_view.latest_as_of is None
        assert sub_view.admission_status_counts is None
        external_workflows.list_radar.assert_called_once_with(
            status=None, limit=OPPORTUNITY_RADAR_LIMIT, offset=0
        )
        # Defence-in-depth: the original exception's driver-level
        # detail never leaks into the public response field.
        assert "postgres" not in str(sub_view)
        assert "secret" not in str(sub_view)


class TestOpportunityUnknownExceptionPropagation:
    """Unknown exceptions from the radar reader propagate."""

    def test_unknown_exception_propagates_through_opportunity_path(self) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            opportunity_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestCandidatePoolAndOpportunityDoNotAffectTopLevelState:
    """The Slice 2B sub-segments must not perturb the Slice 1 state machine."""

    @pytest.mark.parametrize(
        "candidate_pool_return",
        [
            None,
            CandidatePoolQueryError("boom"),
            CandidatePoolSnapshotMissingError(
                snapshot_id=uuid4(), run_id=uuid4()
            ),
        ],
    )
    @pytest.mark.parametrize(
        "opportunity_return",
        [
            [],
            [_observation()],
            OperationalError("SELECT", {}, Exception("boom")),
        ],
    )
    def test_slice_2b_failures_keep_market_state_machine_intact(
        self,
        candidate_pool_return,
        opportunity_return,
    ) -> None:
        service, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            candidate_pool_return=candidate_pool_return,
            opportunity_return=opportunity_return,
        )

        response = service.get_research_center()

        # The Slice 1 four-state derivation is governed solely by the
        # breadth / freshness sources; the new sub-segments stay out
        # of the top-level state machine until a later slice folds
        # them in.
        assert response.state == "available"
        assert response.market.state == "available"


__all__ = [
    "TestAsOfDateResolution",
    "TestCandidatePoolAndOpportunityDoNotAffectTopLevelState",
    "TestCandidatePoolSummaryAvailable",
    "TestCandidatePoolSummaryEmpty",
    "TestCandidatePoolSummaryFailure",
    "TestCandidatePoolUnknownExceptionPropagation",
    "TestCapabilityBundle",
    "TestObservationMapping",
    "TestOpportunitySummaryAvailable",
    "TestOpportunitySummaryEmpty",
    "TestOpportunitySummaryFailure",
    "TestOpportunityUnknownExceptionPropagation",
    "TestResearchSummaryAvailable",
    "TestResearchSummaryDoNotAffectTopLevelState",
    "TestResearchSummaryEmpty",
    "TestResearchSummaryFailure",
    "TestResearchUnknownExceptionPropagation",
    "TestStateDerivation",
    "TestUnknownExceptionPropagation",
]
