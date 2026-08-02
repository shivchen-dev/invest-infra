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

A third regression target is the *latest*-attempt selection in
:func:`invest_pipeline.etf_daily_bars.upsert_etf_daily_bars`. The
storage layer's :meth:`SqlAlchemyProviderAttemptRepository.list_by_request`
returns attempts ordered by ``attempt_no ASC`` per the project
convention, so a naive ``next(succeeded)`` over the result picks the
OLDEST succeeded attempt — wrong whenever an old ``fixture_dev``
baseline attempt co-exists with a fresh ``cifangquant`` run for the
same logical request. The :class:`UpsertEtfDailyBarsLatestAttemptSelectionTest`
suite below pins the explicit ``max(finished_at, attempt_no)``
selection by faking both the storage order and the
``fixture_dev`` / ``cifangquant`` sidecar payloads.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

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
    serialize_daily_bars,
)
from invest_pipeline.etf_daily_bars import (
    upsert_etf_daily_bars,
    write_etf_daily_bars_raw,
)
from invest_storage.models import ProviderAttemptRow, ProviderRequestRow
from invest_storage.repositories import (
    NewProviderRequest,
    SqlAlchemyDailyBarRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session


class _FakeUnitOfWork:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` wired to a mock session.

    Mirrors the shape used by ``test_etf_instruments_asset`` so the
    service can exercise its real repository code paths without
    booting PostgreSQL. ``session.add`` records every persisted row
    so the test can inspect the sidecar stored on the attempt row.

    ``request_log`` is shared across every UoW instance the factory
    hands out for a given session so
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` honours
    the natural ``uq_provider_requests_logical_key`` constraint at
    the fake layer: a repeat call with the same
    ``(provider_key, dataset_key, request_key)`` returns the row
    inserted by the first call instead of producing a duplicate.
    """

    def __init__(
        self, session: MagicMock, *, request_log: list[ProviderRequestRow]
    ) -> None:
        self._session = session
        self._request_log = request_log
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)

    def _get_or_create(self, request: NewProviderRequest) -> StoredProviderRequest:
        for row in self._request_log:
            if (
                row.provider_key == request.provider_key
                and row.dataset_key == request.dataset_key
                and row.request_key == request.request_key
            ):
                return StoredProviderRequest(
                    id=row.id,
                    provider_key=row.provider_key,
                    dataset_key=row.dataset_key,
                    request_key=row.request_key,
                    request_params=dict(row.request_params or {}),
                    requested_by_run_id=row.requested_by_run_id,
                    status=row.status,
                )
        new_row = ProviderRequestRow(
            id=uuid4(),
            provider_key=request.provider_key,
            dataset_key=request.dataset_key,
            request_key=request.request_key,
            request_params=dict(request.request_params),
            requested_by_run_id=request.requested_by_run_id,
            status=request.status,
        )
        self._session.add(new_row)
        self._request_log.append(new_row)
        return StoredProviderRequest(
            id=new_row.id,
            provider_key=new_row.provider_key,
            dataset_key=new_row.dataset_key,
            request_key=new_row.request_key,
            request_params=dict(new_row.request_params or {}),
            requested_by_run_id=new_row.requested_by_run_id,
            status=new_row.status,
        )

    def _list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[StoredProviderAttempt]:
        """Return attempts the fake has actually persisted for ``request_id``.

        Mirrors :meth:`SqlAlchemyProviderAttemptRepository.list_by_request`
        against the in-memory ``session.added_rows`` so the raw write
        path's rerun attempt-numbering logic (max existing
        ``attempt_no`` + 1) sees the attempts the previous run
        inserted.
        """

        matched = sorted(
            (
                row
                for row in self._session.added_rows
                if isinstance(row, ProviderAttemptRow)
                and row.provider_request_id == request_id
            ),
            key=lambda row: row.attempt_no,
        )
        return [
            StoredProviderAttempt(
                id=row.id,
                provider_request_id=row.provider_request_id,
                attempt_no=row.attempt_no,
                started_at=row.started_at,
                finished_at=row.finished_at,
                status=row.status,
                error_stage=row.error_stage,
                error_code=row.error_code,
                error_message=row.error_message,
                response_payload_sha256=row.response_payload_sha256,
                response_payload_json=row.response_payload_json,
            )
            for row in matched[offset : offset + limit]
        ]

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
    log: list[ProviderRequestRow] = []

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(session, request_log=log)

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


class WriteEtfDailyBarsRawCifangquantSidecarTest(unittest.TestCase):
    """The sidecar must surface the real ``request.provider_key``.

    Regression: the previous ``serialize_daily_bars`` call hard-coded
    ``source_provider='fixture_dev'`` so a CifangQuant run would leak the
    fixture identifier into ``core.daily_bars.source_provider`` and break
    any downstream consumer that key off the audit column. The fixture
    paths must keep working, so the fix has to preserve
    ``provider_key='fixture_dev'`` as the default while threading the
    real key through the call site.
    """

    def setUp(self) -> None:
        from datetime import datetime as _dt

        observed = _dt(2026, 7, 28, 8, 0, 0, tzinfo=UTC)

        class _StubProvider:
            """CifangQuant-shaped stub that returns one bar with provider_key='cifangquant'."""

            @property
            def provider_key(self) -> str:
                return "cifangquant"

            def fetch_daily_bars(
                self,
                symbols: list[str],
                start_date: date,
                end_date: date,
            ) -> tuple[Any, Any, Any]:
                attempt_id = uuid4()
                request = MagicMock(name="ProviderRequest")
                request.provider_key = "cifangquant"
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
                bar = DailyBar.build(
                    instrument_id=InstrumentId.generate(),
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
                        provider_key="cifangquant",
                        source_batch_id=attempt_id,
                        observed_at=observed,
                    ),
                    revision=1,
                )
                batch = MagicMock(name="ProviderBatch")
                batch.attempt_id = attempt_id
                batch.records = (bar,)
                batch.raw_payload_hash = "0" * 64
                batch.status = ProviderBatchStatus.SUCCEEDED
                batch.warnings = ()
                return request, attempt, batch

            def symbol_for_instrument_id(
                self, instrument_id: InstrumentId
            ) -> str | None:
                # Cifangquant placeholder table for "510300": the
                # service resolves via reverse lookup against the
                # provider's own ``_placeholder_cache``. Wire a
                # minimal cache so symbol resolution works.
                _ = instrument_id
                return "510300"

        self._stub = _StubProvider()
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._uow_factory = _make_uow_factory(self._session)

    def test_cifangquant_run_records_cifangquant_as_source_provider(self) -> None:
        """Regression: ``source_provider`` on the sidecar must match ``request.provider_key``."""

        write_etf_daily_bars_raw(
            self._stub,
            self._factory,
            symbols=["510300"],
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 28),
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        parsed = json.loads(payload)
        records = parsed["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(
            {entry["source_provider"] for entry in records},
            {"cifangquant"},
        )
        # The fixture identity must never leak into the sidecar.
        self.assertNotIn("fixture_dev", {entry["source_provider"] for entry in records})

    def test_fixture_run_remains_on_fixture_dev(self) -> None:
        """Backwards-compat: fixture_dev's own sidecar stays on 'fixture_dev'."""

        provider = FixtureDevInstrumentProvider()
        write_etf_daily_bars_raw(
            provider,
            self._factory,
            symbols=["510300"],
            start_date=date(2026, 7, 24),
            end_date=date(2026, 7, 28),
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        parsed = json.loads(payload)
        records = parsed["records"]
        self.assertGreater(len(records), 0)
        self.assertEqual(
            {entry["source_provider"] for entry in records},
            {"fixture_dev"},
        )


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


class WriteEtfDailyBarsRawIdempotentRerunTest(unittest.TestCase):
    """A rerun must reuse the existing ``raw.provider_requests`` row
    (no ``uq_provider_requests_logical_key`` violation) and still
    record a fresh attempt + batch so the audit trail captures the
    rerun. ``attempt_no`` must be derived from the persisted attempts
    (max + 1) so the ``uq_provider_attempts_request_attempt_no``
    constraint holds across reruns even though the fixture provider
    keeps returning ``attempt_number=1``.
    """

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()
        self._start = date(2026, 7, 24)
        self._end = date(2026, 7, 28)
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._uow_factory = _make_uow_factory(self._session)

    def test_rerun_reuses_logical_request_and_appends_attempt(self) -> None:
        first = write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        second = write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        third = write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        # The logical request is reused — same UUID, no new row in
        # ``raw.provider_requests`` across the reruns.
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.request_id, third.request_id)
        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(
            len(request_rows),
            1,
            "get_or_create must not re-insert the existing request row",
        )

        # The audit trail still grows — a fresh attempt is recorded
        # for every rerun, with ``attempt_no`` derived from the
        # existing attempts so the
        # ``uq_provider_attempts_request_attempt_no`` constraint is
        # satisfied across reruns (the fixture provider keeps returning
        # ``attempt_number=1``).
        self.assertNotEqual(first.attempt_id, second.attempt_id)
        self.assertNotEqual(second.attempt_id, third.attempt_id)
        attempt_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 3)
        attempt_nos = sorted(row.attempt_no for row in attempt_rows)
        self.assertEqual(attempt_nos, [1, 2, 3])
        for row in attempt_rows:
            self.assertEqual(row.provider_request_id, first.request_id)

    def test_first_run_preserves_provider_attempt_number(self) -> None:
        """First-run ``attempt_no`` honours the value the provider returns.

        Guards against the rerun-fix accidentally forcing every attempt
        to ``max(existing)+1``: a fresh logical request has no existing
        attempts, so ``attempt.attempt_number`` (currently ``1`` for the
        fixture_dev adapter) must still flow through.
        """

        result = write_etf_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["510300"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        attempt_rows = [
            row
            for row in self._session.added_rows
            if isinstance(row, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(attempt_rows[0].id, result.attempt_id)
        self.assertEqual(attempt_rows[0].attempt_no, 1)


# ---------------------------------------------------------------------------
# ``upsert_etf_daily_bars`` latest-attempt selection
# ---------------------------------------------------------------------------


class _UpsertFakeUnitOfWork:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` exercising the read path.

    The raw-write tests above drive the real ``SqlAlchemy*Repository``
    classes against a :class:`MagicMock` session so the in-memory
    ``add`` log records every persisted row. The upsert path is a
    pure read-then-write — there is nothing to persist — so this fake
    stubs the four read methods the service touches
    (``provider_requests.get_by_logical_key``,
    ``provider_attempts.list_by_request``,
    ``instruments.get_by_business_key``) and captures every call to
    ``daily_bars.upsert_many`` so the test can assert which sidecar
    payload drove the ``core.daily_bars`` write.

    The fake intentionally keeps ``provider_attempts.list_by_request``
    as a plain ``MagicMock`` whose ``return_value`` the caller can
    reshape per test, so a test can simulate the storage layer's
    ``attempt_no ASC`` ordering, the opposite ``DESC`` ordering, or
    a busy request with dozens of attempts that would have been
    truncated by the legacy ``limit=10``.
    """

    def __init__(
        self,
        session: MagicMock,
        *,
        stored_request: StoredProviderRequest | None,
        attempts: list[StoredProviderAttempt],
        instrument_lookup: Any,
        upsert_calls: list[list[Any]],
    ) -> None:
        self._session = session
        self._stored_request = stored_request
        self._attempts = attempts
        self._instrument_lookup = instrument_lookup
        self._upsert_calls = upsert_calls

        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._daily_bars = SqlAlchemyDailyBarRepository(session)

        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_by_logical_key = MagicMock(  # type: ignore[method-assign]
            return_value=stored_request
        )
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = MagicMock(  # type: ignore[method-assign]
            return_value=list(attempts)
        )
        self._instruments.get_by_business_key = MagicMock(  # type: ignore[method-assign]
            side_effect=instrument_lookup
        )
        self._daily_bars.upsert_many = MagicMock(  # type: ignore[method-assign]
            side_effect=self._record_upsert_call
        )

    def _record_upsert_call(self, bars: Any) -> list[Any]:
        snapshot = list(bars)
        self._upsert_calls.append(snapshot)
        return snapshot

    @property
    def provider_requests(self) -> SqlAlchemyProviderRequestRepository:
        return self._provider_requests

    @property
    def provider_attempts(self) -> SqlAlchemyProviderAttemptRepository:
        return self._provider_attempts

    @property
    def instruments(self) -> SqlAlchemyInstrumentRepository:
        return self._instruments

    @property
    def daily_bars(self) -> SqlAlchemyDailyBarRepository:
        return self._daily_bars

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _UpsertFakeUnitOfWork:
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


def _build_upsert_session() -> MagicMock:
    """Return a ``MagicMock(spec=Session)`` for the upsert read path."""

    session = MagicMock(name="Session", spec=Session)
    session.commit.return_value = None
    session.rollback.return_value = None
    session.close.return_value = None
    return session


def _make_session_factory(session: MagicMock) -> MagicMock:
    return MagicMock(name="SessionProvider", return_value=session)


def _build_uow_factory(
    session: MagicMock,
    *,
    stored_request: StoredProviderRequest | None,
    attempts: list[StoredProviderAttempt],
    instrument_lookup: Any,
    upsert_calls: list[list[Any]],
) -> tuple[Any, list[_UpsertFakeUnitOfWork]]:
    """Return ``(factory, created_uows)`` so tests can inspect the call args.

    The factory hands out a fresh :class:`_UpsertFakeUnitOfWork` per
    call (mirroring the production context manager), so the test cannot
    simply re-invoke the factory and grab the last instance — each
    invocation would yield a fresh ``list_by_request`` MagicMock. The
    closure-tracked ``created_uows`` list captures every UoW the
    factory hands out so a test can assert on the actual ``call_args``
    the upsert service used.
    """

    created_uows: list[_UpsertFakeUnitOfWork] = []

    def _factory(*_args: Any, **_kwargs: Any) -> _UpsertFakeUnitOfWork:
        uow = _UpsertFakeUnitOfWork(
            session,
            stored_request=stored_request,
            attempts=attempts,
            instrument_lookup=instrument_lookup,
            upsert_calls=upsert_calls,
        )
        created_uows.append(uow)
        return uow

    return (
        MagicMock(name="UnitOfWorkFactory", side_effect=_factory),
        created_uows,
    )


def _build_daily_bars_sidecar(
    *,
    provider_key: str,
    close_price: str,
    source_batch_id: UUID,
    observed_at: datetime,
    trade_date: date = date(2026, 7, 28),
    symbol: str = "510300",
) -> str:
    """Build a valid :func:`serialize_daily_bars` payload for a single bar.

    The upsert path deserialises the JSONB sidecar through
    :func:`deserialize_daily_bars` and expects every record to carry
    the standard ``symbol / trade_date / OHLCV / source_provider /
    source_batch_id / observed_at`` keys. The ``close_price`` is the
    single field the regression suite varies between attempts — the
    ``fixture_dev`` baseline carries ``3.10`` and the fresh
    ``cifangquant`` run carries ``3.20`` so a test that picks the
    wrong attempt can be caught by an explicit assertion on the
    value flowing into ``core.daily_bars``.
    """

    return serialize_daily_bars(
        [
            {
                "symbol": symbol,
                "trade_date": trade_date.isoformat(),
                "open": close_price,
                "high": close_price,
                "low": close_price,
                "close": close_price,
                "prev_close": close_price,
                "volume": "1000",
                "amount": "1000000",
                "trading_status": "normal",
            }
        ],
        source_batch_id=source_batch_id,
        observed_at=observed_at,
        provider_key=provider_key,
    )


def _stored_attempt(
    *,
    attempt_no: int,
    status: str,
    provider_key: str,
    close_price: str,
    started_at: datetime,
    finished_at: datetime,
    provider_request_id: UUID,
) -> StoredProviderAttempt:
    """Return a fully-formed :class:`StoredProviderAttempt` for the read path."""

    batch_id = uuid4()
    sidecar = _build_daily_bars_sidecar(
        provider_key=provider_key,
        close_price=close_price,
        source_batch_id=batch_id,
        observed_at=finished_at,
    )
    return StoredProviderAttempt(
        id=batch_id,
        provider_request_id=provider_request_id,
        attempt_no=attempt_no,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        response_payload_sha256="0" * 64,
        response_payload_json=sidecar,
    )


def _instrument_lookup(
    *, exchange: str, symbol: str
) -> Any:
    """Resolve ``(exchange, symbol)`` to a minimal :class:`Instrument` stub.

    The service only reads ``instrument.instrument_id`` off the result;
    a MagicMock stand-in is sufficient and keeps the regression suite
    independent of the full domain model graph.
    """

    if symbol != "510300":
        return None
    return MagicMock(
        name="Instrument",
        instrument_id=InstrumentId.generate(),
    )


class UpsertEtfDailyBarsLatestAttemptSelectionTest(unittest.TestCase):
    """``upsert_etf_daily_bars`` must consume the LATEST succeeded sidecar.

    The storage layer's
    :meth:`SqlAlchemyProviderAttemptRepository.list_by_request` returns
    attempts ordered by ``attempt_no ASC`` — picking the first
    succeeded row therefore reads the OLDEST attempt, not the latest.
    When an old ``fixture_dev`` baseline attempt co-exists with a
    fresh ``cifangquant`` run for the same logical request, the
    legacy code would silently upsert the stale fixture sidecar into
    ``core.daily_bars``.

    The service fixes this by selecting ``max(finished_at, attempt_no)``
    over the succeeded attempts and asking the storage layer for a
    large enough slice to avoid truncation. The tests below pin the
    new behaviour end-to-end:

    * ascending storage order with a stale ``fixture_dev`` attempt
      followed by a fresh ``cifangquant`` attempt selects cifangquant;
    * descending storage order is tolerated (the selection is
      order-independent);
    * a busy request with >10 attempts is no longer truncated to the
      oldest slice;
    * mixed failed / succeeded runs pick the latest succeeded;
    * missing request rows or zero succeeded attempts raise
      :class:`LookupError` (no silent zero-row upsert).
    """

    def setUp(self) -> None:
        self._provider_key = "cifangquant"
        self._request_key = (
            "daily-bars-2026-07-28-2026-07-28-510300"
        )
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key=self._provider_key,
            dataset_key="etf_daily_bars",
            request_key=self._request_key,
            request_params={},
            status="succeeded",
        )

    def test_old_fixture_then_new_cifang_picks_cifang(self) -> None:
        """The fresh ``cifangquant`` attempt wins over the stale ``fixture_dev``.

        Regression for the production bug: the storage layer returns
        attempts ordered by ``attempt_no ASC`` so the OLD ``fixture_dev``
        baseline is at index 0 of the slice. A naive ``next(succeeded)``
        would lock in the stale sidecar. The service must explicitly
        walk the slice and pick the latest.
        """

        old_attempt = _stored_attempt(
            attempt_no=1,
            status="succeeded",
            provider_key="fixture_dev",
            close_price="3.10",
            started_at=datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 8, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        cifang_attempt = _stored_attempt(
            attempt_no=2,
            status="succeeded",
            provider_key="cifangquant",
            close_price="3.20",
            started_at=datetime(2026, 7, 28, 9, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 9, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        session = _build_upsert_session()
        upsert_calls: list[list[Any]] = []
        uow_factory, _created_uows = _build_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=[old_attempt, cifang_attempt],
            instrument_lookup=_instrument_lookup,
            upsert_calls=upsert_calls,
        )

        summary = upsert_etf_daily_bars(
            _make_session_factory(session),
            provider_key=self._provider_key,
            request_key=self._request_key,
            unit_of_work_factory=uow_factory,
        )

        # The CIFANG attempt's sidecar must flow into ``core.daily_bars``.
        self.assertEqual(summary.total, 1)
        self.assertEqual(len(upsert_calls), 1)
        bars = upsert_calls[0]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, Decimal("3.20"))
        self.assertEqual(bars[0].source.provider_key, "cifangquant")
        # The fixture sidecar must never reach ``core.daily_bars``.
        for call in upsert_calls:
            for bar in call:
                self.assertNotEqual(bar.source.provider_key, "fixture_dev")
                self.assertNotEqual(bar.close, Decimal("3.10"))

    def test_descending_storage_order_still_picks_latest(self) -> None:
        """The selection is order-independent.

        The fake returns attempts in storage order (``DESC``). The
        service's ``max(...)`` must still resolve the most recent
        succeeded attempt — the production DB layer happens to return
        ``ASC`` today, but a future migration to ``DESC`` (e.g. for
        an "attempts newest first" dashboard query) must not silently
        regress the upsert.
        """

        cifang_attempt = _stored_attempt(
            attempt_no=2,
            status="succeeded",
            provider_key="cifangquant",
            close_price="3.20",
            started_at=datetime(2026, 7, 28, 9, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 9, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        old_attempt = _stored_attempt(
            attempt_no=1,
            status="succeeded",
            provider_key="fixture_dev",
            close_price="3.10",
            started_at=datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 8, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        session = _build_upsert_session()
        upsert_calls: list[list[Any]] = []
        uow_factory, _created_uows = _build_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=[cifang_attempt, old_attempt],
            instrument_lookup=_instrument_lookup,
            upsert_calls=upsert_calls,
        )

        summary = upsert_etf_daily_bars(
            _make_session_factory(session),
            provider_key=self._provider_key,
            request_key=self._request_key,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary.total, 1)
        bars = upsert_calls[0]
        self.assertEqual(bars[0].close, Decimal("3.20"))
        self.assertEqual(bars[0].source.provider_key, "cifangquant")

    def test_many_attempts_are_not_truncated_to_oldest_succeeded(self) -> None:
        """A busy request must not lose its latest succeeded attempt.

        The legacy code asked the storage layer for ``limit=10``; a
        frequently-recollected logical request with a dozen failed /
        succeeded attempts would have the OLDEST slice returned and
        miss the fresh cifangquant attempt entirely. The fix asks for
        a slice large enough to cover a busy request and explicitly
        walks it for the latest succeeded attempt.
        """

        early_failures: list[StoredProviderAttempt] = []
        # Ten fixture_dev succeeded attempts — older than the legacy
        # ``limit=10`` ceiling so the slice must NOT be truncated.
        for no in range(1, 11):
            early_failures.append(
                _stored_attempt(
                    attempt_no=no,
                    status="succeeded",
                    provider_key="fixture_dev",
                    close_price="3.10",
                    started_at=datetime(
                        2026, 7, 27, 8, no, 0, tzinfo=UTC
                    ),
                    finished_at=datetime(
                        2026, 7, 27, 8, no, 5, tzinfo=UTC
                    ),
                    provider_request_id=self._provider_request_id,
                )
            )
        failed_attempt = _stored_attempt(
            attempt_no=11,
            status="failed",
            provider_key="cifangquant",
            close_price="0",
            started_at=datetime(2026, 7, 28, 7, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 7, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        latest_cifang = _stored_attempt(
            attempt_no=12,
            status="succeeded",
            provider_key="cifangquant",
            close_price="3.20",
            started_at=datetime(2026, 7, 28, 9, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 9, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        # Storage returns ASC: the fresh cifang attempt is at the END
        # of the slice. The legacy ``limit=10`` would have truncated it
        # away; the fix must walk the full slice.
        session = _build_upsert_session()
        upsert_calls: list[list[Any]] = []
        attempts = early_failures + [failed_attempt, latest_cifang]
        self.assertEqual(len(attempts), 12)
        uow_factory, created_uows = _build_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=_instrument_lookup,
            upsert_calls=upsert_calls,
        )

        summary = upsert_etf_daily_bars(
            _make_session_factory(session),
            provider_key=self._provider_key,
            request_key=self._request_key,
            unit_of_work_factory=uow_factory,
        )

        # The fake UoW exposes the requested slice; the fix must ask
        # for the full population so the latest succeeded attempt is
        # visible. The ``created_uows`` list captures the UoW the
        # factory actually handed out so the test can inspect the
        # ``list_by_request`` call args without re-invoking the
        # factory (which would produce a fresh MagicMock with no
        # recorded call history).
        self.assertEqual(len(created_uows), 1)
        attempts_call = (
            created_uows[0].provider_attempts.list_by_request.call_args
        )
        self.assertIsNotNone(attempts_call)
        self.assertEqual(
            attempts_call.kwargs.get("limit"),
            1000,
            "upsert must request a slice large enough to cover a busy "
            "request; the legacy limit=10 silently truncated the "
            "fresh cifangquant attempt",
        )

        self.assertEqual(summary.total, 1)
        bars = upsert_calls[0]
        self.assertEqual(bars[0].close, Decimal("3.20"))
        self.assertEqual(bars[0].source.provider_key, "cifangquant")

    def test_only_failed_attempts_raises_lookup_error(self) -> None:
        """Zero ``succeeded`` attempts is a hard error, not a silent zero-row upsert.

        Mirrors the legacy contract for the "no successful attempt"
        case: the surface stays loud so a stale downstream trigger
        never silently produces zero ``core.daily_bars`` rows.
        """

        failed_old = _stored_attempt(
            attempt_no=1,
            status="failed",
            provider_key="fixture_dev",
            close_price="0",
            started_at=datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 8, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        failed_new = _stored_attempt(
            attempt_no=2,
            status="failed",
            provider_key="cifangquant",
            close_price="0",
            started_at=datetime(2026, 7, 28, 9, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 28, 9, 0, 5, tzinfo=UTC),
            provider_request_id=self._provider_request_id,
        )
        session = _build_upsert_session()
        upsert_calls: list[list[Any]] = []
        uow_factory, _created_uows = _build_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=[failed_old, failed_new],
            instrument_lookup=_instrument_lookup,
            upsert_calls=upsert_calls,
        )

        with self.assertRaises(LookupError):
            upsert_etf_daily_bars(
                _make_session_factory(session),
                provider_key=self._provider_key,
                request_key=self._request_key,
                unit_of_work_factory=uow_factory,
            )
        # No ``core.daily_bars`` row may be written for a failed run.
        self.assertEqual(upsert_calls, [])

    def test_missing_request_row_raises_lookup_error(self) -> None:
        """No persisted request is a hard error, not a silent zero-row upsert."""

        session = _build_upsert_session()
        upsert_calls: list[list[Any]] = []
        uow_factory, _created_uows = _build_uow_factory(
            session,
            stored_request=None,
            attempts=[],
            instrument_lookup=_instrument_lookup,
            upsert_calls=upsert_calls,
        )

        with self.assertRaises(LookupError):
            upsert_etf_daily_bars(
                _make_session_factory(session),
                provider_key=self._provider_key,
                request_key=self._request_key,
                unit_of_work_factory=uow_factory,
            )
        self.assertEqual(upsert_calls, [])


if __name__ == "__main__":
    unittest.main()
