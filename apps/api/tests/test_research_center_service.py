"""Tests for :class:`ResearchCenterQueryService`.

Bypasses the HTTP layer and the storage readers: constructs the real
:class:`ResearchCenterQueryService` against lightweight mocks of the
two upstream application services so the Slice 1 contract state
machine, observation mapping, capability placeholders, ``as_of_date``
resolution and narrow per-source error boundary can be asserted in
isolation.

Only :class:`MarketBreadthQueryError` and
:class:`DataFreshnessQueryError` are translated into a missing or
failed sub-segment; any other exception must propagate so the router's
generic error boundary stays in charge of sanitising driver-level
detail.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_api.application.data_freshness import (
    DataFreshnessQueryError,
    DataFreshnessQueryService,
    DataFreshnessView,
)
from invest_api.application.market_breadth import (
    MarketBreadthQueryError,
    MarketBreadthQueryService,
)
from invest_api.application.research_center import (
    SCHEMA_VERSION,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterQueryService,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus

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


def _service_with(
    *,
    breadth_return: MarketObservationSnapshot | None | Exception = None,
    freshness_return: DataFreshnessView | None | Exception = None,
) -> tuple[ResearchCenterQueryService, MagicMock, MagicMock]:
    breadth = MagicMock(
        name="MarketBreadthQueryService", spec=MarketBreadthQueryService
    )
    freshness = MagicMock(
        name="DataFreshnessQueryService", spec=DataFreshnessQueryService
    )
    if isinstance(breadth_return, Exception):
        breadth.get_latest.side_effect = breadth_return
    else:
        breadth.get_latest.return_value = breadth_return
    if isinstance(freshness_return, Exception):
        freshness.get_freshness.side_effect = freshness_return
    else:
        freshness.get_freshness.return_value = freshness_return
    return (
        ResearchCenterQueryService(breadth, freshness),
        breadth,
        freshness,
    )


def test_schema_version_constant_is_frozen_at_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


class TestStateDerivation:
    """Coverage for the four-state vocabulary pinned by the Slice 0 contract."""

    def test_both_fresh_and_complete_returns_available(self) -> None:
        service, _, _ = _service_with(
            breadth_return=_snapshot(),
            freshness_return=_freshness_view(status="fresh"),
        )

        response = service.get_research_center()

        assert response.state == "available"
        assert response.market.state == "available"

    def test_breadth_missing_with_usable_freshness_returns_partial(self) -> None:
        service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
            service, _, _ = _service_with(
                breadth_return=MarketBreadthQueryError("breadth failed"),
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
            service, _, _ = _service_with(
                breadth_return=boom,
                freshness_return=_freshness_view(status="fresh"),
            )
        else:
            service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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
        service, _, _ = _service_with(
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


__all__ = [
    "TestAsOfDateResolution",
    "TestCapabilityBundle",
    "TestObservationMapping",
    "TestStateDerivation",
    "TestUnknownExceptionPropagation",
]
