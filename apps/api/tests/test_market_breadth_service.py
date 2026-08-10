"""Tests for :class:`invest_api.application.market_breadth.MarketBreadthQueryService`.

The endpoint tests in :mod:`tests.test_market_breadth_endpoints` mock
the application service at the FastAPI boundary and verify the HTTP
contract. These tests bypass the HTTP layer: they construct the real
service against a mock reader so they can assert the scope-filter
contract (``market_breadth`` / ``ashare_active_universe_v1``), the
optional ``as_of_date`` passthrough, the None-when-missing state and
the :class:`sqlalchemy.exc.SQLAlchemyError` translation to
:class:`MarketBreadthQueryError`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_api.application.market_breadth import (
    SCOPE_KEY,
    SCOPE_TYPE,
    MarketBreadthQueryError,
    MarketBreadthQueryService,
)
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus
from sqlalchemy.exc import OperationalError


def _snapshot() -> MarketObservationSnapshot:
    return MarketObservationSnapshot(
        input_snapshot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        as_of_date=date(2026, 8, 7),
        observations=(
            MarketObservation(
                observation_key="advancing_ratio",
                value=Decimal("0.6"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_breadth",
            ),
            MarketObservation(
                observation_key="declining_ratio",
                value=Decimal("0.3"),
                unit="ratio",
                observed_date=date(2026, 8, 7),
                source_kind="computed",
                source_ref="calc:market_breadth",
            ),
        ),
        quality_status=QualityStatus.COMPLETE,
        freshness_status=FreshnessStatus.FRESH,
    )


def _build_service(reader: MagicMock) -> MarketBreadthQueryService:
    return MarketBreadthQueryService(reader)


class TestScopeConstants:
    """The service pins the breadth scope so callers cannot widen it."""

    def test_scope_type_is_market_breadth(self) -> None:
        assert SCOPE_TYPE == "market_breadth"

    def test_scope_key_is_ashare_active_universe_v1(self) -> None:
        assert SCOPE_KEY == "ashare_active_universe_v1"


class TestGetLatest:
    """Coverage for the no-argument and explicit-date code paths."""

    def test_get_latest_passes_pinned_scope_and_none_date(self) -> None:
        snapshot = _snapshot()
        reader = MagicMock(name="MarketBreadthReader")
        reader.get_latest_for_scope.return_value = snapshot
        service = _build_service(reader)

        result = service.get_latest()

        assert result is snapshot
        reader.get_latest_for_scope.assert_called_once_with(
            SCOPE_TYPE, SCOPE_KEY, None
        )

    def test_get_latest_forwards_explicit_as_of_date(self) -> None:
        snapshot = _snapshot()
        reader = MagicMock(name="MarketBreadthReader")
        reader.get_latest_for_scope.return_value = snapshot
        service = _build_service(reader)

        target = date(2026, 8, 7)
        result = service.get_latest(target)

        assert result is snapshot
        reader.get_latest_for_scope.assert_called_once_with(
            SCOPE_TYPE, SCOPE_KEY, target
        )

    def test_get_latest_returns_none_when_reader_finds_nothing(self) -> None:
        reader = MagicMock(name="MarketBreadthReader")
        reader.get_latest_for_scope.return_value = None
        service = _build_service(reader)

        result = service.get_latest()

        assert result is None
        reader.get_latest_for_scope.assert_called_once_with(
            SCOPE_TYPE, SCOPE_KEY, None
        )


class TestSqlAlchemyErrorBoundary:
    """Coverage for the :class:`MarketBreadthQueryError` translation."""

    def test_translates_sqlalchemy_error_to_query_error(self) -> None:
        reader = MagicMock(name="MarketBreadthReader")
        original = OperationalError(
            "SELECT snapshot",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )
        reader.get_latest_for_scope.side_effect = original
        service = _build_service(reader)

        with pytest.raises(MarketBreadthQueryError) as exc_info:
            service.get_latest()

        assert exc_info.value.__cause__ is original
        assert str(exc_info.value) == "Market breadth query failed"

    def test_query_error_is_runtime_error_subclass(self) -> None:
        assert issubclass(MarketBreadthQueryError, RuntimeError)


class TestProtocol:
    """Coverage that the reader Protocol accepts structurally-compatible mocks."""

    def test_accepts_structurally_compatible_reader(self) -> None:
        class _CompatibleReader:
            def get_latest_for_scope(
                self,
                scope_type: str,
                scope_key: str,
                as_of_date: date | None = None,
            ) -> MarketObservationSnapshot | None:
                return _snapshot()

        service = MarketBreadthQueryService(_CompatibleReader())  # type: ignore[arg-type]
        result = service.get_latest(date(2026, 8, 7))
        assert result is not None
        assert result.snapshot_id == _snapshot().snapshot_id


__all__ = [
    "TestGetLatest",
    "TestProtocol",
    "TestScopeConstants",
    "TestSqlAlchemyErrorBoundary",
]