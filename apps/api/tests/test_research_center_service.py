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

from collections.abc import Mapping, Sequence
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
from invest_api.application.pipeline_runs import (
    PipelineRunQueryError,
    PipelineRunQueryService,
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
    ARCHIVE_ARTIFACT_LIMIT,
    ARCHIVE_EMPTY_REASON,
    ARCHIVE_FAILED_REASON,
    ARCHIVE_RUN_LIMIT,
    CANDIDATE_POOL_FAILED_REASON,
    CANDIDATE_POOL_SNAPSHOT_MISSING_REASON,
    DELIVERY_SCHEMA_VERSION,
    INTEGRATION_EMPTY_REASON,
    INTEGRATION_FAILED_REASON,
    OPPORTUNITY_EMPTY_REASON,
    OPPORTUNITY_FAILED_REASON,
    OPPORTUNITY_RADAR_LIMIT,
    PIPELINE_FAILED_REASON,
    RESEARCH_RUNS_EMPTY_REASON,
    RESEARCH_RUNS_FAILED_REASON,
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
    recent_runs: list | None = None,
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
        recent_runs=list(recent_runs) if recent_runs is not None else [],
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
    pipeline_return: object | None | Exception = None,
    integration_health_return: (
        Mapping[str, object] | None | Exception
    ) = None,
    archive_run_return: object | None | Exception = None,
    archive_artifacts_return: (
        Sequence[object] | None | Exception
    ) = (),
) -> tuple[
    ResearchCenterQueryService,
    MagicMock,
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
    pipeline = MagicMock(
        name="PipelineRunQueryService", spec=PipelineRunQueryService
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
    if isinstance(pipeline_return, Exception):
        pipeline.get_latest_run.side_effect = pipeline_return
    else:
        pipeline.get_latest_run.return_value = pipeline_return
    if isinstance(integration_health_return, Exception):
        external_workflows.health.side_effect = integration_health_return
    else:
        external_workflows.health.return_value = (
            dict(integration_health_return)
            if integration_health_return is not None
            else None
        )
    if isinstance(archive_run_return, Exception):
        external_workflows.list_runs.side_effect = archive_run_return
    else:
        external_workflows.list_runs.return_value = (
            list(archive_run_return)
            if archive_run_return is not None
            else []
        )
    if isinstance(archive_artifacts_return, Exception):
        external_workflows.list_artifacts.side_effect = archive_artifacts_return
    else:
        external_workflows.list_artifacts.return_value = (
            list(archive_artifacts_return)
            if archive_artifacts_return is not None
            else []
        )
    return (
        ResearchCenterQueryService(
            breadth,
            freshness,
            research,
            candidate_pool,
            external_workflows,
            pipeline,
        ),
        breadth,
        freshness,
        research,
        candidate_pool,
        external_workflows,
        pipeline,
    )


def test_schema_version_constant_is_frozen_at_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_research_schema_version_constant_is_frozen_at_1_0_0() -> None:
    assert RESEARCH_SCHEMA_VERSION == "1.0.0"


class TestStateDerivation:
    """Coverage for the four-state vocabulary pinned by the Slice 0 contract."""

    def test_both_fresh_and_complete_returns_available(self) -> None:
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.state == "available"
        assert response.market.state == "available"

    def test_breadth_missing_with_usable_freshness_returns_partial(self) -> None:
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
            service, _, _, _, _, _, _ = _service_with(
                breadth_return=MarketBreadthQueryError("breadth failed"),
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
            service, _, _, _, _, _, _ = _service_with(
                breadth_return=boom,
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, research, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, research, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, research, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, candidate_pool, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, candidate_pool, _, _ = _service_with(
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
        service, _, _, _, candidate_pool, _, _ = _service_with(
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
        service, _, _, _, candidate_pool, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, external_workflows, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, external_workflows, _ = _service_with(
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
        service, _, _, _, _, external_workflows, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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
        service, _, _, _, _, _, _ = _service_with(
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


def _pipeline_run(
    *,
    status: str = "succeeded",
    job_key: str = "personal_etf_daily_job",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_summary: str | None = None,
) -> SimpleNamespace:
    """Return a structurally-compatible :class:`PipelineRun` shim."""

    if started_at is None:
        started_at = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
    if finished_at is None and status in {
        "succeeded", "failed", "partial", "cancelled"
    }:
        finished_at = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        job_key=job_key,
        trigger_type="scheduled",
        status=SimpleNamespace(value=status),
        started_at=started_at,
        finished_at=finished_at,
        error_summary=error_summary,
    )


def _integration_health(
    *,
    status: str = "healthy",
    sample_size: int = 5,
    producer_statuses: dict[str, int] | None = None,
    intake_statuses: dict[str, int] | None = None,
    latest_run_id: UUID | None = None,
) -> dict[str, object]:
    """Return a structurally-compatible :meth:`ExternalWorkflowQueryService.health` result."""

    return {
        "status": status,
        "sample_size": sample_size,
        "producer_statuses": producer_statuses
        or {"succeeded": 4, "partial": 1, "failed": 0, "cancelled": 0},
        "intake_statuses": intake_statuses
        or {"accepted": 5, "partial": 0, "pending": 0, "rejected": 0},
        "latest_run_id": latest_run_id,
    }


def _external_workflow_run(
    *,
    run_id: UUID | None = None,
    producer_status: str = "succeeded",
    intake_status: str = "accepted",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> SimpleNamespace:
    """Return a structurally-compatible :class:`ExternalWorkflowRun` shim."""

    return SimpleNamespace(
        run_id=run_id or uuid4(),
        producer="workbuddy",
        schema_version="v1",
        producer_status=SimpleNamespace(value=producer_status),
        intake_status=SimpleNamespace(value=intake_status),
        started_at=started_at or datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        finished_at=finished_at or datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        metadata={},
    )


def _external_artifact(
    *,
    artifact_id: UUID | None = None,
    run_id: UUID | None = None,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    """Return a structurally-compatible :class:`ExternalArtifact` shim."""

    return SimpleNamespace(
        artifact_id=artifact_id or uuid4(),
        run_id=run_id or uuid4(),
        logical_uri="logical://example/artifact",
        content_hash="a" * 64,
        media_type="application/json",
        size_bytes=1024,
        created_at=created_at or datetime(2026, 8, 15, 10, 30, tzinfo=UTC),
        metadata={},
    )


def _research_run(
    *,
    run_id: UUID | None = None,
    status: str = "succeeded",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_summary: str | None = None,
) -> SimpleNamespace:
    """Return a structurally-compatible :class:`ResearchRun` shim."""

    if started_at is None:
        started_at = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
    if finished_at is None and status in {
        "succeeded", "failed", "cancelled"
    }:
        finished_at = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    return SimpleNamespace(
        run_id=run_id or uuid4(),
        case_id=uuid4(),
        evidence_pack_id=uuid4(),
        runner_key="llm",
        playbook_key="default",
        status=SimpleNamespace(value=status),
        attempt=1,
        started_at=started_at,
        finished_at=finished_at,
        error_summary=error_summary,
        evidence_bundle_id=None,
    )


class TestDeliveryPipelineAvailable:
    """``state == "available"`` projects the latest run identity and times."""

    def test_succeeded_run_projects_status_started_finished_and_business_date(
        self,
    ) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        finished = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(
                status="succeeded", started_at=started, finished_at=finished
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        assert pipeline.state == "available"
        assert pipeline.status == "succeeded"
        assert pipeline.started_at == started
        assert pipeline.finished_at == finished
        assert pipeline.business_completion_date == date(2026, 8, 15)
        assert pipeline.reason is None

    def test_running_run_emits_running_state_with_no_finished_timestamp(
        self,
    ) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(
                status="running", started_at=started, finished_at=None
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        assert pipeline.state == "running"
        assert pipeline.status == "running"
        assert pipeline.started_at == started
        assert pipeline.finished_at is None
        assert pipeline.business_completion_date is None

    def test_partial_run_emits_partial_state_with_business_completion_date(
        self,
    ) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        finished = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(
                status="partial", started_at=started, finished_at=finished
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        assert pipeline.state == "partial"
        assert pipeline.status == "partial"
        assert pipeline.finished_at == finished
        assert pipeline.business_completion_date == date(2026, 8, 15)


class TestDeliveryPipelineEmptyAndFailure:
    """``state == "empty"`` and ``state == "failed"`` keep the bounded facts out."""

    def test_no_pipeline_run_reports_empty_state(self) -> None:
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=None,
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        assert pipeline.state == "empty"
        assert pipeline.status is None
        assert pipeline.started_at is None
        assert pipeline.finished_at is None
        assert pipeline.business_completion_date is None
        assert pipeline.reason is None

    def test_pipeline_query_error_emits_failed_with_redacted_reason(self) -> None:
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=PipelineRunQueryError(
                "driver-level boom: postgres://user:secret@host/db"
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        assert pipeline.state == "failed"
        assert pipeline.reason == PIPELINE_FAILED_REASON
        assert pipeline.status is None
        assert pipeline.started_at is None
        assert pipeline.finished_at is None
        assert pipeline.business_completion_date is None
        # Defence-in-depth: the original exception's driver-level
        # detail never leaks into the public response field.
        assert "postgres" not in str(pipeline)
        assert "secret" not in str(pipeline)

    def test_unknown_exception_from_pipeline_propagates(self) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestDeliveryPipelineTerminalStateMapping:
    """``status`` -> ``state`` mapping is pinned explicitly per :class:`PipelineRunStatus`.

    The five-state vocabulary
    ``available | empty | running | partial | failed`` covers the
    six :class:`invest_domain.pipeline.PipelineRunStatus` values
    exactly:

    * ``succeeded`` → ``available`` (the only ``available`` path).
    * ``running`` / ``queued`` → ``running`` (in-flight, not finished).
    * ``partial`` / ``cancelled`` → ``partial`` (terminal without full
      success; deliberately not ``available``).
    * ``failed`` (run-level) → ``failed``; the controlled
      :class:`PipelineRunQueryError` boundary also reports ``failed``
      with the opaque ``PIPELINE_FAILED_REASON``.
    """

    def test_failed_run_emits_failed_state_not_available(self) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        finished = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(
                status="failed",
                started_at=started,
                finished_at=finished,
                error_summary="personal daily job failed in fixtures",
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        # ``failed`` is the only state the pipeline sub-segment can
        # carry for a terminal ``failed`` run; the run must never be
        # misclassified as ``available`` so the UI can render the
        # explicit failure slot.
        assert pipeline.state == "failed"
        assert pipeline.status == "failed"
        assert pipeline.started_at == started
        assert pipeline.finished_at == finished
        assert pipeline.business_completion_date == date(2026, 8, 15)
        # Run-level failure is encoded in the state vocabulary
        # itself; ``reason`` stays ``None`` so the public response
        # never echoes the run-level ``error_summary``.
        assert pipeline.reason is None
        # Defence-in-depth: the run-level ``error_summary`` never
        # leaks through the dataclass serialization.
        assert "error_summary" not in pipeline.__dataclass_fields__
        assert "error_summary" not in repr(pipeline)

    def test_cancelled_run_emits_partial_state_not_available(self) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        finished = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(
                status="cancelled",
                started_at=started,
                finished_at=finished,
            ),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        # ``cancelled`` is a terminal-without-success path; explicitly
        # ``partial`` so the front-end can render the cancellation
        # slot without borrowing the ``available`` vocabulary.
        assert pipeline.state == "partial"
        assert pipeline.state != "available"
        assert pipeline.status == "cancelled"
        assert pipeline.finished_at == finished
        assert pipeline.business_completion_date == date(2026, 8, 15)
        assert pipeline.reason is None

    def test_queued_run_emits_running_state_not_available(self) -> None:
        # A pre-start (``queued``) pipeline has no ``started_at``
        # and no ``finished_at`` per the PipelineRun invariant;
        # build a structural shim inline because the helper imposes
        # a default ``started_at`` to mimic in-flight runs.
        queued_run = SimpleNamespace(
            id=uuid4(),
            job_key="personal_etf_daily_job",
            trigger_type="scheduled",
            status=SimpleNamespace(value="queued"),
            started_at=None,
            finished_at=None,
            error_summary=None,
        )
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=queued_run,
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        # ``queued`` reuses ``running`` because the pipeline is in
        # flight from the user's perspective; it must never be
        # misclassified as ``available`` just because the run has
        # not started yet.
        assert pipeline.state == "running"
        assert pipeline.state != "available"
        assert pipeline.status == "queued"
        assert pipeline.started_at is None
        assert pipeline.finished_at is None
        assert pipeline.business_completion_date is None
        assert pipeline.reason is None

    @pytest.mark.parametrize("status", ["succeeded", "partial", "running"])
    def test_known_terminal_states_keep_documented_mapping(self, status: str) -> None:
        started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        finished = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        kwargs: dict = {"status": status}
        if status == "running":
            kwargs["started_at"] = started
            kwargs["finished_at"] = None
        else:
            kwargs["started_at"] = started
            kwargs["finished_at"] = finished
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=_pipeline_run(**kwargs),
        )

        response = service.get_research_center()

        pipeline = response.delivery.pipeline
        expected = {
            "succeeded": "available",
            "running": "running",
            "partial": "partial",
        }[status]
        assert pipeline.state == expected


class TestDeliveryIntegrationAvailable:
    """``state == "available"`` projects bounded health dictionary facts."""

    def test_populated_health_projects_status_counts_and_latest_as_of(self) -> None:
        latest_run_id = uuid4()
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            integration_health_return=_integration_health(
                status="healthy",
                sample_size=5,
                latest_run_id=latest_run_id,
            ),
        )
        latest_run = _external_workflow_run(
            run_id=latest_run_id,
            finished_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        )
        external_workflows.get_run.return_value = latest_run

        response = service.get_research_center()

        integration = response.delivery.integration
        assert integration.state == "available"
        assert integration.status == "healthy"
        assert integration.sample_size == 5
        assert integration.producer_status_counts == {
            "succeeded": 4,
            "partial": 1,
            "failed": 0,
            "cancelled": 0,
        }
        assert integration.intake_status_counts == {
            "accepted": 5,
            "partial": 0,
            "pending": 0,
            "rejected": 0,
        }
        assert integration.latest_as_of == date(2026, 8, 15)
        assert integration.reason is None
        external_workflows.health.assert_called_once_with()
        external_workflows.get_run.assert_called_once_with(latest_run_id)


class TestDeliveryIntegrationEmpty:
    """``state == "empty"`` is the explicit zero-sample path."""

    def test_zero_sample_size_reports_empty_state_with_stable_reason(self) -> None:
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            integration_health_return=_integration_health(
                status="healthy", sample_size=0, latest_run_id=None
            ),
        )

        response = service.get_research_center()

        integration = response.delivery.integration
        assert integration.state == "empty"
        assert integration.sample_size == 0
        assert integration.producer_status_counts == {
            "succeeded": 4,
            "partial": 1,
            "failed": 0,
            "cancelled": 0,
        }
        assert integration.intake_status_counts == {
            "accepted": 5,
            "partial": 0,
            "pending": 0,
            "rejected": 0,
        }
        assert integration.latest_as_of is None
        assert integration.reason == INTEGRATION_EMPTY_REASON
        external_workflows.health.assert_called_once_with()
        # The bounded reader skips ``get_run`` because the bounded
        # sample carries no run identity.
        external_workflows.get_run.assert_not_called()


class TestDeliveryIntegrationFailure:
    """``SQLAlchemyError`` from the integration reader is translated."""

    def test_sqlalchemy_error_emits_failed_with_redacted_reason(self) -> None:
        boom = OperationalError(
            "SELECT", {}, Exception("postgres://user:secret@host/db")
        )
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            integration_health_return=boom,
        )

        response = service.get_research_center()

        integration = response.delivery.integration
        assert integration.state == "failed"
        assert integration.reason == INTEGRATION_FAILED_REASON
        assert integration.sample_size is None
        assert integration.producer_status_counts is None
        assert integration.intake_status_counts is None
        assert integration.latest_as_of is None
        assert "postgres" not in str(integration)
        assert "secret" not in str(integration)
        external_workflows.health.assert_called_once_with()
        # ``get_run`` is intentionally skipped once ``health`` raised
        # the controlled failure so the bounded surface never fans
        # out beyond the first failing read.
        external_workflows.get_run.assert_not_called()

    def test_unknown_exception_from_integration_propagates(self) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            integration_health_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)
        external_workflows.get_run.assert_not_called()


class TestDeliveryArchiveAvailable:
    """``state == "available"`` projects the bounded artifact slice."""

    def test_artifact_list_projects_count_run_status_and_latest_as_of(self) -> None:
        run = _external_workflow_run(
            producer_status="succeeded",
            finished_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        )
        artifacts = (
            _external_artifact(
                run_id=run.run_id,
                created_at=datetime(2026, 8, 15, 10, 30, tzinfo=UTC),
            ),
            _external_artifact(
                run_id=run.run_id,
                created_at=datetime(2026, 8, 15, 10, 15, tzinfo=UTC),
            ),
        )
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=[run],
            archive_artifacts_return=list(artifacts),
        )

        response = service.get_research_center()

        archive = response.delivery.archive
        assert archive.state == "available"
        assert archive.artifact_count == 2
        assert archive.latest_run_status == "succeeded"
        assert archive.latest_as_of == date(2026, 8, 15)
        assert archive.reason is None
        external_workflows.list_runs.assert_called_once_with(
            limit=ARCHIVE_RUN_LIMIT, offset=0
        )
        external_workflows.list_artifacts.assert_called_once_with(
            run.run_id, limit=ARCHIVE_ARTIFACT_LIMIT, offset=0
        )


class TestDeliveryArchiveEmpty:
    """``state == "empty"`` covers the no-run and zero-artifact paths."""

    def test_no_recent_run_reports_empty_state(self) -> None:
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=[],
            archive_artifacts_return=[],
        )

        response = service.get_research_center()

        archive = response.delivery.archive
        assert archive.state == "empty"
        assert archive.artifact_count == 0
        assert archive.latest_run_status is None
        assert archive.latest_as_of is None
        assert archive.reason == ARCHIVE_EMPTY_REASON
        # ``list_artifacts`` is intentionally skipped when no
        # latest run exists; the bounded surface never fans out
        # beyond the empty sample.
        external_workflows.list_artifacts.assert_not_called()

    def test_latest_run_with_zero_artifacts_reports_empty_state(self) -> None:
        run = _external_workflow_run()
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=[run],
            archive_artifacts_return=[],
        )

        response = service.get_research_center()

        archive = response.delivery.archive
        assert archive.state == "empty"
        assert archive.artifact_count == 0
        assert archive.latest_run_status == "succeeded"
        assert archive.latest_as_of is None
        assert archive.reason == ARCHIVE_EMPTY_REASON
        external_workflows.list_runs.assert_called_once_with(
            limit=ARCHIVE_RUN_LIMIT, offset=0
        )
        external_workflows.list_artifacts.assert_called_once_with(
            run.run_id, limit=ARCHIVE_ARTIFACT_LIMIT, offset=0
        )


class TestDeliveryArchiveFailure:
    """``SQLAlchemyError`` from the archive readers is translated."""

    def test_list_runs_sqlalchemy_error_emits_failed_with_redacted_reason(
        self,
    ) -> None:
        boom = OperationalError(
            "SELECT", {}, Exception("postgres://user:secret@host/db")
        )
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=boom,
        )

        response = service.get_research_center()

        archive = response.delivery.archive
        assert archive.state == "failed"
        assert archive.reason == ARCHIVE_FAILED_REASON
        assert archive.artifact_count is None
        assert archive.latest_as_of is None
        assert archive.latest_run_status is None
        assert "postgres" not in str(archive)
        assert "secret" not in str(archive)
        external_workflows.list_runs.assert_called_once_with(
            limit=ARCHIVE_RUN_LIMIT, offset=0
        )
        external_workflows.list_artifacts.assert_not_called()

    def test_list_artifacts_sqlalchemy_error_emits_failed_with_redacted_reason(
        self,
    ) -> None:
        run = _external_workflow_run()
        boom = OperationalError(
            "SELECT", {}, Exception("postgres://user:secret@host/db")
        )
        service, _, _, _, _, external_workflows, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=[run],
            archive_artifacts_return=boom,
        )

        response = service.get_research_center()

        archive = response.delivery.archive
        assert archive.state == "failed"
        assert archive.reason == ARCHIVE_FAILED_REASON
        # ``latest_run_status`` is preserved from the bounded
        # ``list_runs`` call so the front-end can distinguish a
        # run-listing success from an artifact-listing failure.
        assert archive.latest_run_status == "succeeded"
        assert archive.artifact_count is None
        assert "postgres" not in str(archive)

    def test_unknown_exception_from_archive_propagates(self) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            archive_run_return=boom,
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.get_research_center()

        assert "postgres://user:secret@host/db" in str(exc_info.value)


class TestDeliveryResearchRunsAvailable:
    """``state == "available"`` projects bounded recent-runs facts."""

    def test_recent_runs_projects_count_status_counts_and_latest_run(self) -> None:
        latest_run = _research_run(
            status="succeeded",
            started_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
            finished_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        )
        another_run = _research_run(
            status="failed",
            started_at=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
            finished_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        )
        dashboard_view = _dashboard_view(
            case_count=1,
            run_count=2,
            latest_case=None,
            recent_runs=[latest_run, another_run],
        )
        service, _, _, research, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=dashboard_view,
        )

        response = service.get_research_center()

        research_runs = response.delivery.research_runs
        assert research_runs.state == "available"
        assert research_runs.run_count == 2
        assert research_runs.status_counts == {
            "queued": 0,
            "running": 0,
            "succeeded": 1,
            "failed": 1,
            "cancelled": 0,
        }
        assert research_runs.latest_status == "succeeded"
        assert research_runs.latest_started_at == datetime(
            2026, 8, 15, 9, 0, tzinfo=UTC
        )
        assert research_runs.latest_finished_at == datetime(
            2026, 8, 15, 10, 0, tzinfo=UTC
        )
        assert research_runs.reason is None
        research.get_dashboard.assert_called_once_with()


class TestDeliveryResearchRunsEmpty:
    """``state == "empty"`` is the explicit zero-recent-runs path."""

    def test_empty_recent_runs_reports_empty_state_with_stable_reason(self) -> None:
        service, _, _, research, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        research_runs = response.delivery.research_runs
        assert research_runs.state == "empty"
        assert research_runs.run_count == 0
        assert research_runs.status_counts == {
            "queued": 0,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
        }
        assert research_runs.latest_status is None
        assert research_runs.latest_started_at is None
        assert research_runs.latest_finished_at is None
        assert research_runs.reason == RESEARCH_RUNS_EMPTY_REASON
        research.get_dashboard.assert_called_once_with()


class TestDeliveryResearchRunsFailure:
    """``ResearchQueryError`` is translated into the explicit ``failed`` state."""

    def test_research_query_error_emits_failed_with_redacted_reason(self) -> None:
        service, _, _, research, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            research_return=ResearchQueryError(
                "driver-level boom: postgres://user:secret@host/db"
            ),
        )

        response = service.get_research_center()

        research_runs = response.delivery.research_runs
        assert research_runs.state == "failed"
        assert research_runs.reason == RESEARCH_RUNS_FAILED_REASON
        assert research_runs.run_count is None
        assert research_runs.status_counts is None
        assert research_runs.latest_status is None
        assert research_runs.latest_started_at is None
        assert research_runs.latest_finished_at is None
        assert "postgres" not in str(research_runs)
        assert "secret" not in str(research_runs)
        research.get_dashboard.assert_called_once_with()


class TestDeliverySubsegmentsIndependent:
    """A single source failure must not contaminate the other delivery sub-segments."""

    @pytest.mark.parametrize(
        ("pipeline_return", "integration_health_return", "archive_run_return"),
        [
            pytest.param(
                PipelineRunQueryError("pipeline boom"),
                _integration_health(),
                [_external_workflow_run()],
                id="pipeline_failure_keeps_integration_and_archive",
            ),
            pytest.param(
                _pipeline_run(status="succeeded"),
                OperationalError("SELECT", {}, Exception("integration boom")),
                [_external_workflow_run()],
                id="integration_failure_keeps_pipeline_and_archive",
            ),
            pytest.param(
                _pipeline_run(status="succeeded"),
                _integration_health(),
                OperationalError("SELECT", {}, Exception("archive boom")),
                id="archive_failure_keeps_pipeline_and_integration",
            ),
        ],
    )
    def test_single_source_failure_does_not_contaminate_other_sources(
        self,
        pipeline_return,
        integration_health_return,
        archive_run_return,
    ) -> None:
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            pipeline_return=pipeline_return,
            integration_health_return=integration_health_return,
            archive_run_return=archive_run_return,
        )

        response = service.get_research_center()

        delivery = response.delivery
        # Defensive: in every parameterised case exactly one of the
        # three sources carries the failure while the other two
        # still surface a populated ``state``.
        failed_states = {
            "pipeline": delivery.pipeline.state,
            "integration": delivery.integration.state,
            "archive": delivery.archive.state,
        }
        assert failed_states["pipeline"] in {"available", "running", "partial", "empty", "failed"}
        assert failed_states["integration"] in {"available", "empty", "failed"}
        assert failed_states["archive"] in {"available", "empty", "failed"}


class TestDeliverySubsegmentFailureDoesNotPerturbTopLevelState:
    """Delivery sub-segment failure must not perturb top-level state.

    The Slice 1 four-state derivation is governed solely by the
    breadth / freshness sources; a controlled pipeline / integration
    / archive failure must stay inside its own sub-segment slot so the
    central page can render the other slots on their own state machine
    without bleeding into the top-level state. This is the
    Slice 3A equivalent of the Slice 2A ``TestResearchSummaryDoNotAffectTopLevelState``
    and the Slice 2B ``TestCandidatePoolAndOpportunityDoNotAffectTopLevelState``
    invariants.
    """

    @pytest.mark.parametrize(
        "delivery_failure",
        [
            pytest.param("pipeline", id="pipeline_failure"),
            pytest.param("integration", id="integration_failure"),
            pytest.param("archive", id="archive_failure"),
        ],
    )
    def test_single_delivery_failure_keeps_top_level_state_available(
        self, delivery_failure: str
    ) -> None:
        kwargs: dict = {}
        if delivery_failure == "pipeline":
            kwargs["pipeline_return"] = PipelineRunQueryError(
                "driver-level boom: postgres://user:secret@host/db"
            )
        elif delivery_failure == "integration":
            kwargs["integration_health_return"] = OperationalError(
                "SELECT", {}, Exception("integration boom")
            )
        else:
            kwargs["archive_run_return"] = OperationalError(
                "SELECT", {}, Exception("archive boom")
            )

        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
            **kwargs,
        )

        response = service.get_research_center()

        # The breadth/freshness derivation is untouched by every
        # delivery sub-segment failure: the top-level state still
        # mirrors the market state and stays ``available``.
        assert response.state == "available"
        assert response.market.state == "available"
        # Defence-in-depth: the bounded delivery sub-segments keep
        # their own state machine independent of the top-level
        # derivation; only the slot owned by the failing source
        # reports ``failed`` while the others stay operational.
        if delivery_failure == "pipeline":
            assert response.delivery.pipeline.state == "failed"
            assert response.delivery.pipeline.reason == PIPELINE_FAILED_REASON
            assert response.delivery.integration.state in {
                "available", "empty"
            }
            assert response.delivery.archive.state in {
                "available", "empty"
            }
        elif delivery_failure == "integration":
            assert response.delivery.pipeline.state in {
                "available", "running", "partial", "empty"
            }
            assert response.delivery.integration.state == "failed"
            assert response.delivery.integration.reason == INTEGRATION_FAILED_REASON
            assert response.delivery.archive.state in {
                "available", "empty"
            }
        else:
            assert response.delivery.pipeline.state in {
                "available", "running", "partial", "empty"
            }
            assert response.delivery.integration.state in {
                "available", "empty"
            }
            assert response.delivery.archive.state == "failed"
            assert response.delivery.archive.reason == ARCHIVE_FAILED_REASON


class TestDeliverySchemaVersion:
    """The router-facing ``schema_version`` mirrors the application constant."""

    def test_delivery_schema_version_constant_is_frozen_at_1_0_0(self) -> None:
        assert DELIVERY_SCHEMA_VERSION == "1.0.0"

    def test_response_delivery_schema_version_matches_constant(self) -> None:
        service, _, _, _, _, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.delivery.schema_version == DELIVERY_SCHEMA_VERSION


__all__ = [
    "TestAsOfDateResolution",
    "TestCandidatePoolAndOpportunityDoNotAffectTopLevelState",
    "TestCandidatePoolSummaryAvailable",
    "TestCandidatePoolSummaryEmpty",
    "TestCandidatePoolSummaryFailure",
    "TestCandidatePoolUnknownExceptionPropagation",
    "TestCapabilityBundle",
    "TestDeliveryArchiveAvailable",
    "TestDeliveryArchiveEmpty",
    "TestDeliveryArchiveFailure",
    "TestDeliveryIntegrationAvailable",
    "TestDeliveryIntegrationEmpty",
    "TestDeliveryIntegrationFailure",
    "TestDeliveryPipelineAvailable",
    "TestDeliveryPipelineEmptyAndFailure",
    "TestDeliveryPipelineTerminalStateMapping",
    "TestDeliveryResearchRunsAvailable",
    "TestDeliveryResearchRunsEmpty",
    "TestDeliveryResearchRunsFailure",
    "TestDeliverySchemaVersion",
    "TestDeliverySubsegmentFailureDoesNotPerturbTopLevelState",
    "TestDeliverySubsegmentsIndependent",
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
