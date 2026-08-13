"""Tests for the stock price-limits ETL service.

- ``write_stock_price_limits_raw`` persists the PR-02 three-layer
  evidence bundle and stamps a deterministic sidecar on the attempt.
- ``upsert_stock_price_limits`` reads the LATEST succeeded attempt
  sidecar, resolves ``core.instruments.id`` per ``(exchange,
  instrument_id)`` and hands ``NewPriceLimit`` rows to
  ``stock_price_limits.upsert_many`` so the repository's revision
  semantics drive the actual write.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_pipeline.adapters.fixture_dev.price_limits import (
    FixtureDevStockPriceLimitsProvider,
)
from invest_pipeline.stock_price_limits import (
    PriceLimitUpsertSummary,
    RawEtlResult,
    deserialize_stock_price_limits,
    serialize_stock_price_limits,
    upsert_stock_price_limits,
    write_stock_price_limits_raw,
)
from invest_storage.models import ProviderAttemptRow, ProviderRequestRow
from invest_storage.repositories import (
    NewPriceLimit,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    SqlAlchemyStockPriceLimitRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session

_FIXTURE_DATE = date(2026, 8, 11)
_OBSERVED_AT = datetime(2026, 8, 11, 8, 0, 0, tzinfo=UTC)
_TRADE_DATE = _FIXTURE_DATE


class _FakeWriteUnitOfWork:
    """Write-path UoW stub: shares one request log across UoWs and tracks ``session.add``."""

    def __init__(self, session: MagicMock, *, request_log: list[ProviderRequestRow]) -> None:
        self._session = session
        self._request_log = request_log
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)

    def _get_or_create(self, request: Any) -> StoredProviderRequest:
        for row in self._request_log:
            if (
                row.provider_key == request.provider_key
                and row.dataset_key == request.dataset_key
                and row.request_key == request.request_key
            ):
                return _stored_request(row)
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
        return _stored_request(new_row)

    def _list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[StoredProviderAttempt]:
        matched = sorted(
            (
                r
                for r in self._session.added_rows
                if isinstance(r, ProviderAttemptRow)
                and r.provider_request_id == request_id
            ),
            key=lambda r: r.attempt_no,
        )
        return [
            StoredProviderAttempt(
                id=r.id,
                provider_request_id=r.provider_request_id,
                attempt_no=r.attempt_no,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                error_stage=r.error_stage,
                error_code=r.error_code,
                error_message=r.error_message,
                response_payload_sha256=r.response_payload_sha256,
                response_payload_json=r.response_payload_json,
            )
            for r in matched[offset : offset + limit]
        ]

    provider_requests = property(lambda self: self._provider_requests)
    provider_attempts = property(lambda self: self._provider_attempts)
    provider_batches = property(lambda self: self._provider_batches)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _FakeWriteUnitOfWork:
        return self

    def __exit__(self, exc_type, exc, tb):
        (self.rollback() if exc_type is not None else self.commit())
        self._session.close()


class _FakeUpsertUnitOfWork:
    """Read-path UoW stub: pins the read methods and captures ``upsert_many`` calls."""

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
        self._upsert_calls = upsert_calls
        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._stock_price_limits = SqlAlchemyStockPriceLimitRepository(session)
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_by_logical_key = MagicMock(  # type: ignore[method-assign]
            return_value=stored_request,
        )
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = MagicMock(  # type: ignore[method-assign]
            return_value=list(attempts),
        )
        self._instruments.get_by_business_key = MagicMock(  # type: ignore[method-assign]
            side_effect=instrument_lookup,
        )
        self._stock_price_limits.upsert_many = MagicMock(  # type: ignore[method-assign]
            side_effect=self._record_upsert_call,
        )

    def _record_upsert_call(self, limits: Any) -> list[Any]:
        snapshot = list(limits)
        self._upsert_calls.append(snapshot)
        return snapshot

    provider_requests = property(lambda self: self._provider_requests)
    provider_attempts = property(lambda self: self._provider_attempts)
    instruments = property(lambda self: self._instruments)
    stock_price_limits = property(lambda self: self._stock_price_limits)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _FakeUpsertUnitOfWork:
        return self

    def __exit__(self, exc_type, exc, tb):
        (self.rollback() if exc_type is not None else self.commit())
        self._session.close()


def _stored_request(row: ProviderRequestRow) -> StoredProviderRequest:
    return StoredProviderRequest(
        id=row.id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        request_key=row.request_key,
        request_params=dict(row.request_params or {}),
        requested_by_run_id=row.requested_by_run_id,
        status=row.status,
    )


def _build_session() -> MagicMock:
    """Return a ``MagicMock(spec=Session)`` recording ``add`` and resolving ``session.get``."""

    session = MagicMock(name="Session", spec=Session)
    session.added_rows = []
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


def _make_uow_factory(session: MagicMock, *, uow_cls: type, **kwargs: Any) -> MagicMock:
    def _factory(*_a: Any, **_k: Any) -> Any:
        return uow_cls(session, **kwargs)

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _build_write_session() -> tuple[MagicMock, MagicMock, MagicMock]:
    session = _build_session()
    log: list[ProviderRequestRow] = []
    return (
        session,
        _make_session_factory(session),
        _make_uow_factory(session, uow_cls=_FakeWriteUnitOfWork, request_log=log),
    )


def _attempt_payload(session: MagicMock) -> dict[str, Any]:
    rows = [r for r in session.added_rows if isinstance(r, ProviderAttemptRow)]
    assert len(rows) == 1, f"exactly one attempt row, got {len(rows)}"
    payload = rows[0].response_payload_json
    assert payload is not None, "attempt must carry the sidecar"
    return json.loads(str(payload))


def _batch_rows(session: MagicMock) -> list[Any]:
    return [r for r in session.added_rows if type(r).__name__ == "RawProviderBatchRow"]


class WriteStockPriceLimitsRawSuccessTest(unittest.TestCase):
    """Successful attempts persist request + attempt + batch + sidecar."""

    def setUp(self) -> None:
        self._provider = FixtureDevStockPriceLimitsProvider()
        self._session, self._factory, self._uow_factory = _build_write_session()

    def test_persists_request_attempt_batch_and_sidecar(self) -> None:
        result = write_stock_price_limits_raw(
            self._provider,
            self._factory,
            symbols=["600000", "000001"],
            trade_date=_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertIsInstance(result, RawEtlResult)
        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertIsNotNone(result.batch_id)
        self.assertEqual(result.record_count, 2)

        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(request_rows[0].provider_key, "fixture_dev")
        self.assertEqual(request_rows[0].dataset_key, "stock_price_limits")
        self.assertEqual(
            request_rows[0].request_key,
            f"price-limits-{_TRADE_DATE.isoformat()}-600000-000001",
        )

        attempt_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 1)
        attempt_row = attempt_rows[0]
        self.assertEqual(attempt_row.status, "succeeded")
        self.assertEqual(attempt_row.attempt_no, 1)
        self.assertIsNotNone(attempt_row.response_payload_json)
        self.assertIsNotNone(attempt_row.response_payload_sha256)
        self.assertNotEqual(attempt_row.response_payload_sha256, "0" * 64)
        self.assertEqual(len(attempt_row.response_payload_sha256), 64)

        batch_rows = _batch_rows(self._session)
        self.assertEqual(len(batch_rows), 1)
        self.assertEqual(batch_rows[0].record_count, 2)

    def test_sidecar_carries_required_fields_per_record(self) -> None:
        write_stock_price_limits_raw(
            self._provider,
            self._factory,
            symbols=["600000", "000001"],
            trade_date=_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        self.assertEqual(payload["schema_version"], 1)
        records = payload["records"]
        self.assertEqual(len(records), 2)

        batch_id = _batch_rows(self._session)[0].id

        expected_keys = {
            "instrument_id",
            "exchange",
            "trade_date",
            "regime_id",
            "limit_up_price",
            "limit_down_price",
            "status",
            "reference_price",
            "source_provider",
            "observed_at",
            "source_batch_id",
            "row_hash",
        }
        for record in records:
            self.assertEqual(set(record.keys()), expected_keys)
            self.assertEqual(record["source_provider"], "fixture_dev")
            self.assertEqual(record["source_batch_id"], str(batch_id))
            self.assertEqual(record["trade_date"], _TRADE_DATE.isoformat())

        by_symbol = {r["instrument_id"]: r for r in records}
        self.assertEqual(by_symbol["600000"]["exchange"], "SSE")
        self.assertEqual(by_symbol["000001"]["exchange"], "SZSE")
        self.assertEqual(by_symbol["600000"]["status"], "known")
        self.assertEqual(by_symbol["000001"]["status"], "known")
        self.assertEqual(len(by_symbol["600000"]["row_hash"]), 64)


class WriteStockPriceLimitsRawFailureTest(unittest.TestCase):
    """Failed attempts persist request + attempt only; no batch, no core rows."""

    def setUp(self) -> None:
        self._session, self._factory, self._uow_factory = _build_write_session()
        self._provider = FixtureDevStockPriceLimitsProvider(simulate_failure=True)

    def test_failed_attempt_creates_no_batch(self) -> None:
        result = write_stock_price_limits_raw(
            self._provider,
            self._factory,
            symbols=["600000"],
            trade_date=_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertIsNone(result.batch_id)
        self.assertEqual(result.record_count, 0)

        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(request_rows[0].status, "failed")

        attempt_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 1)
        attempt_row = attempt_rows[0]
        self.assertEqual(attempt_row.status, "failed")
        self.assertIsNone(attempt_row.response_payload_json)
        self.assertEqual(attempt_row.error_code, "simulated_failure")

        self.assertEqual(_batch_rows(self._session), [])


class SerializeDeserializeRoundTripTest(unittest.TestCase):
    """The sidecar codec must round-trip byte-for-byte."""

    def test_round_trip_preserves_every_field(self) -> None:
        sidecar_records = [
            {
                "instrument_id": "600000",
                "exchange": "SSE",
                "trade_date": _TRADE_DATE.isoformat(),
                "regime_id": "SSE_MAIN_2023_04_10",
                "limit_up_price": "11.00",
                "limit_down_price": "9.00",
                "status": "known",
                "reference_price": "10.00",
                "row_hash": "a" * 64,
            },
            {
                "instrument_id": "688001",
                "exchange": "SSE",
                "trade_date": _TRADE_DATE.isoformat(),
                "regime_id": "SSE_STAR_2019_07_22",
                "limit_up_price": None,
                "limit_down_price": None,
                "status": "unlimited",
                "reference_price": "10.00",
                "row_hash": "b" * 64,
            },
        ]
        batch_id = uuid4()

        payload = serialize_stock_price_limits(
            sidecar_records,
            source_batch_id=batch_id,
            observed_at=_OBSERVED_AT,
            provider_key="fixture_dev",
        )

        deserialized = deserialize_stock_price_limits(payload)
        self.assertEqual(len(deserialized), 2)

        first = deserialized[0]
        self.assertEqual(first["instrument_id"], "600000")
        self.assertEqual(first["exchange"], "SSE")
        self.assertEqual(first["regime_id"], "SSE_MAIN_2023_04_10")
        self.assertEqual(first["limit_up_price"], "11.00")
        self.assertEqual(first["limit_down_price"], "9.00")
        self.assertEqual(first["status"], "known")
        self.assertEqual(first["reference_price"], "10.00")
        self.assertEqual(first["source_provider"], "fixture_dev")
        self.assertEqual(first["source_batch_id"], str(batch_id))
        self.assertEqual(first["observed_at"], _OBSERVED_AT.isoformat())
        self.assertEqual(first["row_hash"], "a" * 64)

        second = deserialized[1]
        self.assertIsNone(second["limit_up_price"])
        self.assertEqual(second["status"], "unlimited")

    def test_deterministic_payload_byte_identical_across_calls(self) -> None:
        sidecar_records = [
            {
                "instrument_id": "600000",
                "exchange": "SSE",
                "trade_date": _TRADE_DATE.isoformat(),
                "regime_id": "SSE_MAIN_2023_04_10",
                "limit_up_price": "11.00",
                "limit_down_price": "9.00",
                "status": "known",
                "reference_price": "10.00",
                "row_hash": "a" * 64,
            },
        ]
        batch_id = uuid4()
        first = serialize_stock_price_limits(
            sidecar_records,
            source_batch_id=batch_id,
            observed_at=_OBSERVED_AT,
            provider_key="fixture_dev",
        )
        second = serialize_stock_price_limits(
            sidecar_records,
            source_batch_id=batch_id,
            observed_at=_OBSERVED_AT,
            provider_key="fixture_dev",
        )
        self.assertEqual(first, second)

    def test_unsupported_schema_version_raises(self) -> None:
        bad_payload = json.dumps({"schema_version": 999, "records": []})
        with self.assertRaises(ValueError) as ctx:
            deserialize_stock_price_limits(bad_payload)
        self.assertIn("schema_version", str(ctx.exception))


def _make_limit_record(
    *,
    symbol: str,
    exchange: str,
    reference: str = "10.00",
    regime: str = "SSE_MAIN_2023_04_10",
    status: str = "known",
    up: str | None = "11.00",
    down: str | None = "9.00",
    row_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "instrument_id": symbol,
        "exchange": exchange,
        "trade_date": _TRADE_DATE.isoformat(),
        "regime_id": regime,
        "limit_up_price": up,
        "limit_down_price": down,
        "status": status,
        "reference_price": reference,
        "row_hash": row_hash or ("a" * 64),
    }


def _instrument_lookup(
    known: set[tuple[str, str]],
) -> Any:
    def _lookup(*, exchange: str, symbol: str) -> Any:
        if (exchange, symbol) not in known:
            return None
        inst = MagicMock(name="Instrument")
        inst.instrument_id = MagicMock(name="InstrumentId")
        inst.instrument_id.value = uuid4()
        return inst

    return _lookup


def _stored_attempt(
    *,
    attempt_no: int,
    sidecar_records: list[dict[str, Any]],
    provider_request_id: UUID,
    status: str = "succeeded",
) -> StoredProviderAttempt:
    batch_id = uuid4()
    payload = serialize_stock_price_limits(
        sidecar_records,
        source_batch_id=batch_id,
        observed_at=_OBSERVED_AT,
        provider_key="fixture_dev",
    )
    return StoredProviderAttempt(
        id=batch_id,
        provider_request_id=provider_request_id,
        attempt_no=attempt_no,
        started_at=_OBSERVED_AT,
        finished_at=_OBSERVED_AT,
        status=status,
        response_payload_sha256="0" * 64,
        response_payload_json=payload,
    )


class UpsertStockPriceLimitsMappingTest(unittest.TestCase):
    """The upsert must thread the sidecar ``exchange`` into ``get_by_business_key``."""

    def setUp(self) -> None:
        self._session = _build_session()
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key="fixture_dev",
            dataset_key="stock_price_limits",
            request_key=f"price-limits-{_TRADE_DATE.isoformat()}-600000-000001-999999",
            request_params={},
            status="succeeded",
        )

    def _run(
        self, sidecar: list[dict[str, Any]]
    ) -> tuple[PriceLimitUpsertSummary, list[list[Any]], Any]:
        attempts = [
            _stored_attempt(
                attempt_no=1,
                sidecar_records=sidecar,
                provider_request_id=self._provider_request_id,
            )
        ]
        upsert_calls: list[list[Any]] = []
        known = {("SSE", "600000"), ("SZSE", "000001")}
        lookup = _instrument_lookup(known)
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_FakeUpsertUnitOfWork,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=lookup,
            upsert_calls=upsert_calls,
        )
        summary = upsert_stock_price_limits(
            _make_session_factory(self._session),
            trade_date=_TRADE_DATE,
            symbols=["600000", "000001", "999999"],
            unit_of_work_factory=uow_factory,
        )
        return summary, upsert_calls, lookup

    def test_upsert_threads_exchange_into_business_key_lookup(self) -> None:
        sidecar = [
            _make_limit_record(symbol="600000", exchange="SSE"),
            _make_limit_record(symbol="000001", exchange="SZSE"),
        ]
        summary, upsert_calls, _ = self._run(sidecar)

        self.assertEqual(summary.inserted, 2)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(summary.total, 2)
        self.assertEqual(len(upsert_calls), 1)
        limits = upsert_calls[0]
        self.assertEqual(len(limits), 2)
        for limit in limits:
            self.assertIsInstance(limit, NewPriceLimit)

    def test_unknown_instrument_is_skipped(self) -> None:
        sidecar = [
            _make_limit_record(symbol="600000", exchange="SSE"),
            _make_limit_record(symbol="000001", exchange="SZSE"),
            _make_limit_record(symbol="999999", exchange="SSE"),
        ]
        summary, upsert_calls, _ = self._run(sidecar)

        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.inserted, 2)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(len(upsert_calls[0]), 2)

    def test_exchange_lookup_uses_sidecar_value_not_prefix(self) -> None:
        # ``000001`` registered as ``SSE`` (not the SZSE prefix guess);
        # the upsert must thread ``exchange='SSE'`` from the sidecar
        # and find the active instrument there.
        sidecar = [
            _make_limit_record(symbol="000001", exchange="SSE"),
        ]
        known = {("SSE", "000001")}
        attempts = [
            _stored_attempt(
                attempt_no=1,
                sidecar_records=sidecar,
                provider_request_id=self._provider_request_id,
            )
        ]
        upsert_calls: list[list[Any]] = []
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_FakeUpsertUnitOfWork,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=_instrument_lookup(known),
            upsert_calls=upsert_calls,
        )

        summary = upsert_stock_price_limits(
            _make_session_factory(self._session),
            trade_date=_TRADE_DATE,
            symbols=["000001"],
            unit_of_work_factory=uow_factory,
        )
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(summary.skipped, 0)


class UpsertStockPriceLimitsUnknownStatusTest(unittest.TestCase):
    """Unknown status records must fail closed; no ``core`` rows are written."""

    def setUp(self) -> None:
        self._session = _build_session()
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key="fixture_dev",
            dataset_key="stock_price_limits",
            request_key=f"price-limits-{_TRADE_DATE.isoformat()}-600000",
            request_params={},
            status="succeeded",
        )

    def test_unknown_status_raises_value_error(self) -> None:
        sidecar = [
            _make_limit_record(symbol="600000", exchange="SSE", status="unknown"),
        ]
        attempts = [
            _stored_attempt(
                attempt_no=1,
                sidecar_records=sidecar,
                provider_request_id=self._provider_request_id,
            )
        ]
        known = {("SSE", "600000")}
        upsert_calls: list[list[Any]] = []
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_FakeUpsertUnitOfWork,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=_instrument_lookup(known),
            upsert_calls=upsert_calls,
        )

        with self.assertRaises(ValueError) as ctx:
            upsert_stock_price_limits(
                _make_session_factory(self._session),
                trade_date=_TRADE_DATE,
                symbols=["600000"],
                unit_of_work_factory=uow_factory,
            )
        self.assertIn("unknown", str(ctx.exception).lower())
        self.assertEqual(upsert_calls, [])


class UpsertStockPriceLimitsRevisionHandoffTest(unittest.TestCase):
    """The service must hand the right ``NewPriceLimit`` rows to ``upsert_many``."""

    def setUp(self) -> None:
        self._session = _build_session()
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key="fixture_dev",
            dataset_key="stock_price_limits",
            request_key=f"price-limits-{_TRADE_DATE.isoformat()}-600000",
            request_params={},
            status="succeeded",
        )

    def test_upsert_many_receives_new_price_limits_with_repo_returned_count(self) -> None:
        known_instrument_uuid = uuid4()

        def _lookup(*, exchange: str, symbol: str) -> Any:
            if (exchange, symbol) != ("SSE", "600000"):
                return None
            inst = MagicMock(name="Instrument")
            inst.instrument_id = MagicMock(name="InstrumentId")
            inst.instrument_id.value = known_instrument_uuid
            return inst

        sidecar = [_make_limit_record(symbol="600000", exchange="SSE")]
        attempts = [
            _stored_attempt(
                attempt_no=1,
                sidecar_records=sidecar,
                provider_request_id=self._provider_request_id,
            )
        ]

        upsert_calls: list[list[Any]] = []

        class _CountingRepoUoW(_FakeUpsertUnitOfWork):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self._stock_price_limits.upsert_many = MagicMock(  # type: ignore[method-assign]
                    side_effect=lambda limits: upsert_calls.append(list(limits)) or list(limits)
                )

        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_CountingRepoUoW,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=_lookup,
            upsert_calls=upsert_calls,
        )

        summary = upsert_stock_price_limits(
            _make_session_factory(self._session),
            trade_date=_TRADE_DATE,
            symbols=["600000"],
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary.inserted, 1)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(len(upsert_calls), 1)
        limits = upsert_calls[0]
        self.assertEqual(len(limits), 1)
        limit = limits[0]
        self.assertIsInstance(limit, NewPriceLimit)
        self.assertEqual(limit.instrument_id, known_instrument_uuid)
        self.assertEqual(limit.trade_date, _TRADE_DATE)
        self.assertEqual(limit.regime_id, "SSE_MAIN_2023_04_10")
        self.assertEqual(limit.limit_up_price, Decimal("11.00"))
        self.assertEqual(limit.limit_down_price, Decimal("9.00"))
        self.assertEqual(limit.status, "known")
        self.assertEqual(limit.reference_price, Decimal("10.00"))
        self.assertEqual(limit.source_provider, "fixture_dev")
        self.assertEqual(len(limit.row_hash), 64)

    def test_picks_latest_succeeded_attempt_for_idempotent_rerun(self) -> None:
        old_attempt = _stored_attempt(
            attempt_no=1,
            sidecar_records=[
                _make_limit_record(symbol="600000", exchange="SSE", row_hash="a" * 64)
            ],
            provider_request_id=self._provider_request_id,
        )
        fresh_attempt = _stored_attempt(
            attempt_no=2,
            sidecar_records=[
                _make_limit_record(symbol="600000", exchange="SSE", row_hash="b" * 64)
            ],
            provider_request_id=self._provider_request_id,
        )
        known = {("SSE", "600000")}
        upsert_calls: list[list[Any]] = []
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_FakeUpsertUnitOfWork,
            stored_request=self._stored_request,
            attempts=[old_attempt, fresh_attempt],
            instrument_lookup=_instrument_lookup(known),
            upsert_calls=upsert_calls,
        )

        summary = upsert_stock_price_limits(
            _make_session_factory(self._session),
            trade_date=_TRADE_DATE,
            symbols=["600000"],
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary.inserted, 1)
        self.assertEqual(upsert_calls[0][0].row_hash, "b" * 64)

    def test_missing_request_row_raises_lookup_error(self) -> None:
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_FakeUpsertUnitOfWork,
            stored_request=None,
            attempts=[],
            instrument_lookup=_instrument_lookup(set()),
            upsert_calls=[],
        )

        with self.assertRaises(LookupError):
            upsert_stock_price_limits(
                _make_session_factory(self._session),
                trade_date=_TRADE_DATE,
                symbols=["600000"],
                unit_of_work_factory=uow_factory,
            )


if __name__ == "__main__":
    unittest.main()