"""Unit tests for the PR-06 etf_daily_bars service module.

The sidecar symbol resolution path is the regression target: the
pipeline must serialise the provider-native symbol (e.g.
``"510300"``) into the JSONB sidecar on
``raw.provider_attempts.response_payload_json``, never the
audit-only ``BarSource.provider_key`` (``"fixture_dev"`` /
``"cifangquant"``). The downstream ``etf_daily_bars`` upsert resolves
the real ``core.instruments.id`` from the sidecar's ``symbol`` via
``(symbol, exchange)``; writing ``"fixture_dev"`` instead of
``"510300"`` would make the upsert silently skip every row.

A second regression target is the failure surface: if a provider
hands the service a ``DailyBar`` whose ``instrument_id`` does not
belong to its own placeholder table (a placeholder leak across
provider instances), the service must refuse to persist the sidecar
loudly rather than writing the audit field as the symbol.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttemptStatus,
    ProviderBatchStatus,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.adapters.fixture_dev.adapter import (
    FixtureDevInstrumentProvider,
    deserialize_daily_bars,
)
from invest_pipeline.etf_daily_bars import write_etf_daily_bars_raw
from invest_storage.models import ProviderAttemptRow
from invest_storage.repositories import (
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
)
from sqlalchemy.orm import Session


class _FakeUnitOfWork:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` wired to a mock session.

    Mirrors the shape used by ``test_etf_instruments_asset`` so the
    service can exercise its real repository code paths without
    booting PostgreSQL. ``session.add`` records every persisted row
    so the test can inspect the sidecar stored on the attempt row.
    """

    def __init__(self, session: MagicMock) -> None:
        self._session = session
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)

    @property
    def provider_requests(self) -> SqlAlchemyProviderRequestRepository:
        return self._provider_requests

    @property
    def provider_attempts(self) -> SqlAlchemyProviderAttemptRepository:
        return self._provider_attempts

    @property
    def provider_batches(self) -> SqlAlchemyProviderBatchRepository:
        return self._provider_batches

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self._session.close()


def _build_session() -> MagicMock:
    """Return a ``MagicMock(spec=Session)`` that records every ``add`` call."""

    session = MagicMock(name="Session", spec=Session)
    session.added_rows: list[Any] = []
    session.flush.return_value = None
    session.commit.return_value = None
    session.rollback.return_value = None
    session.close.return_value = None

    def _add(row: Any) -> None:
        session.added_rows.append(row)

    session.add.side_effect = _add

    def _get(_model: Any, primary_key: Any) -> Any:
        for row in session.added_rows:
            if getattr(row, "id", None) == primary_key:
                return row
        return None

    session.get.side_effect = _get
    return session


def _make_session_factory(session: MagicMock) -> MagicMock:
    return MagicMock(name="SessionProvider", return_value=session)


def _make_uow_factory(session: MagicMock) -> MagicMock:
    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(session)

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _attempt_payload(session: MagicMock) -> str:
    attempt_rows = [
        row for row in session.added_rows if isinstance(row, ProviderAttemptRow)
    ]
    assert len(attempt_rows) == 1, f"exactly one attempt row, got {len(attempt_rows)}"
    payload = attempt_rows[0].response_payload_json
    assert payload is not None, "attempt must carry the sidecar"
    return str(payload)


class WriteEtfDailyBarsRawSidecarTest(unittest.TestCase):
    """The JSONB sidecar must carry the provider-native symbol."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()
        self._start = date(2026, 7, 24)
        self._end = date(2026, 7, 28)
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._uow_factory = _make_uow_factory(self._session)

    def test_sidecar_symbol_is_provider_native_not_provider_key(self) -> None:
        """Regression: sidecar ``symbol`` must be ``"510300"``, not ``"fixture_dev"``."""

        write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        parsed = json.loads(payload)
        records = parsed["records"]
        self.assertGreater(len(records), 0, "fixture_dev fixture must yield rows")

        symbols = {entry["symbol"] for entry in records}
        # Regression assertion: the audit field must never leak into the
        # symbol slot. This is the exact bug being fixed.
        self.assertNotIn("fixture_dev", symbols)
        self.assertNotIn("cifangquant", symbols)
        # The full fixture_dev universe must round-trip via the sidecar.
        self.assertEqual(symbols, {"510300"})

        # ``source_provider`` is the audit field — it stays as "fixture_dev".
        providers = {entry["source_provider"] for entry in records}
        self.assertEqual(providers, {"fixture_dev"})

    def test_sidecar_round_trips_via_deserialize_daily_bars(self) -> None:
        """The upsert path uses ``deserialize_daily_bars``; the shape must match."""

        write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        round_tripped = deserialize_daily_bars(payload)
        self.assertEqual(len(round_tripped), 3, "3 trading days in window")
        symbols = sorted(entry["symbol"] for entry in round_tripped)
        self.assertEqual(symbols, ["510300", "510300", "510300"])

    def test_sidecar_multi_symbol_round_trip(self) -> None:
        """Multiple symbols must each map to their provider-native identifier."""

        write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300", "510500"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        parsed = json.loads(payload)
        symbols = sorted({entry["symbol"] for entry in parsed["records"]})
        self.assertEqual(symbols, ["510300", "510500"])

    def test_provider_native_symbol_resolves_for_every_fetched_bar(self) -> None:
        """Every bar returned by ``fetch_daily_bars`` must resolve via the provider."""

        _, _, batch = self._provider.fetch_daily_bars(
            ["510300", "510500"], self._start, self._end
        )
        assert batch is not None
        for bar in batch.records:
            resolved = self._provider.symbol_for_instrument_id(bar.instrument_id)
            self.assertIsNotNone(resolved, f"placeholder {bar.instrument_id} leaked")
            self.assertIn(resolved, {"510300", "510500"})


class WriteEtfDailyBarsRawResolutionFailureTest(unittest.TestCase):
    """The service must refuse to persist when a bar's placeholder leaks."""

    def setUp(self) -> None:
        self._real_provider = FixtureDevInstrumentProvider()
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._uow_factory = _make_uow_factory(self._session)

    def test_unresolvable_instrument_id_raises_lookup_error(self) -> None:
        """A bar carrying an unknown ``InstrumentId`` must surface as ``LookupError``."""

        observed = datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC)
        foreign_id = InstrumentId.generate()
        orphan_bar = DailyBar.build(
            instrument_id=foreign_id,
            trade_date=date(2026, 7, 28),
            open=Decimal("3.10"),
            high=Decimal("3.18"),
            low=Decimal("3.08"),
            close=Decimal("3.15"),
            prev_close=Decimal("3.09"),
            volume=Decimal("1000"),
            amount=Decimal("3150000"),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=BarSource(
                provider_key="fixture_dev",
                source_batch_id=uuid4(),
                observed_at=observed,
            ),
            revision=1,
        )

        class _StubProvider:
            """Stand-in provider whose placeholder table does NOT own ``foreign_id``."""

            @property
            def provider_key(self) -> str:
                return "fixture_dev"

            def fetch_daily_bars(
                self,
                symbols: list[str],
                start_date: date,
                end_date: date,
            ) -> tuple[Any, Any, Any]:
                attempt_id = uuid4()
                request = MagicMock(name="ProviderRequest")
                request.provider_key = "fixture_dev"
                request.dataset_key = "etf_daily_bars"
                request.request_key = (
                    f"daily-bars-{start_date.isoformat()}-"
                    f"{end_date.isoformat()}-{'-'.join(symbols)}"
                )
                request.params = {
                    "symbols": list(symbols),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
                attempt = MagicMock(name="ProviderAttempt")
                attempt.attempt_number = 1
                attempt.status = ProviderAttemptStatus.SUCCEEDED
                attempt.started_at = observed
                attempt.finished_at = observed
                attempt.error_stage = None
                attempt.error_code = None
                attempt.error_message = None
                batch = MagicMock(name="ProviderBatch")
                batch.attempt_id = attempt_id
                batch.records = (orphan_bar,)
                batch.raw_payload_hash = "0" * 64
                batch.status = ProviderBatchStatus.SUCCEEDED
                batch.warnings = ()
                return request, attempt, batch

            def symbol_for_instrument_id(
                self, instrument_id: InstrumentId
            ) -> str | None:
                # Empty placeholder table: every lookup misses.
                return None

        with self.assertRaises(LookupError) as ctx:
            write_etf_daily_bars_raw(
                _StubProvider(),
                self._factory,
                symbols=["510300"],
                start_date=date(2026, 7, 28),
                end_date=date(2026, 7, 28),
                unit_of_work_factory=self._uow_factory,
            )
        message = str(ctx.exception)
        self.assertIn("could not resolve instrument_id", message)
        self.assertIn("fixture_dev", message)


if __name__ == "__main__":
    unittest.main()