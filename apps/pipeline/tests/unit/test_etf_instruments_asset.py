"""Unit tests for the PR-05 ETF instrument Dagster assets.

The two assets under test are thin wrappers around
:func:`invest_pipeline.etf_instruments.write_etf_instruments_raw` and
:func:`invest_pipeline.etf_instruments.upsert_etf_instruments`. To keep
the tests independent of PostgreSQL, the suite injects a custom
UnitOfWork factory (via the ``unit_of_work_factory`` parameter) that
hands out the real ``SqlAlchemy*Repository`` classes wrapping a
:class:`unittest.mock.MagicMock` session. The verification targets the
three contracts the spec calls out:

- ``etf_instruments_raw`` writes ``raw.provider_requests`` +
  ``raw.provider_attempts`` + ``raw.provider_batches`` in the success
  path and the request + attempt only on the failure path (no batch).
- ``etf_instruments`` reads the records back from the attempt's
  ``response_payload_json`` sidecar and upserts them into
  ``core.instruments``.
- Re-running the ETL is idempotent at the ``core.instruments`` layer
  (the upsert repository is invoked with the same payload on a
  re-run).
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from invest_pipeline.adapters.fixture_dev.adapter import (
    FixtureDevInstrumentProvider,
    _serialize_records,
)
from invest_pipeline.etf_instruments import (
    upsert_etf_instruments,
    write_etf_instruments_raw,
)
from invest_storage.models import (
    ProviderAttemptRow,
    ProviderRequestRow,
    RawProviderBatchRow,
)
from invest_storage.repositories import (
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session


class _FakeUnitOfWork:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` that wires the real repos to a mock session.

    The repositories' write paths are exercised against the mock
    session's ``add`` method so the test can introspect the rows the
    service tried to persist without booting a real database. The
    read paths used by :func:`upsert_etf_instruments` are stubbed via
    pre-seeded ``side_effect`` callbacks.
    """

    def __init__(
        self,
        session: MagicMock,
        *,
        request_lookup: Any,
        attempt_list: Any,
        upsert_records: list[list[Instrument]] | None = None,
    ) -> None:
        self._session = session
        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)
        self._request_lookup = request_lookup
        self._attempt_list = attempt_list
        self._upsert_calls = upsert_records if upsert_records is not None else []

        # Wire the read paths to the pre-seeded callbacks.
        self._provider_requests.get_by_logical_key = MagicMock(  # type: ignore[method-assign]
            side_effect=request_lookup
        )
        self._provider_attempts.list_by_request = MagicMock(  # type: ignore[method-assign]
            side_effect=attempt_list
        )
        self._instruments.upsert_many = MagicMock(  # type: ignore[method-assign]
            side_effect=self._record_upsert_call
        )

    def _record_upsert_call(self, instruments: Any) -> int:
        self._upsert_calls.append(list(instruments))
        return len(instruments)

    @property
    def instruments(self) -> SqlAlchemyInstrumentRepository:
        return self._instruments

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


def _build_uow_factory(
    session: MagicMock,
    *,
    request_lookup: Any,
    attempt_list: Any,
    upsert_records: list[list[Instrument]] | None = None,
) -> Any:
    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(
            session,
            request_lookup=request_lookup,
            attempt_list=attempt_list,
            upsert_records=upsert_records,
        )

    return _factory


def _make_attempt_list(
    attempts: list[StoredProviderAttempt],
) -> Any:
    def _list(*_args: Any, **_kwargs: Any) -> list[StoredProviderAttempt]:
        return list(attempts)

    return _list


def _build_session() -> MagicMock:
    """Return a ``MagicMock(spec=Session)`` that records every ``add`` call."""

    session = MagicMock(name="Session", spec=Session)
    session.added_rows: list[Any] = []
    session.flush.return_value = None
    session.commit.return_value = None
    session.rollback.return_value = None
    session.close.return_value = None

    request_ids: dict[UUID, StoredProviderRequest] = {}

    def _add(row: Any) -> None:
        session.added_rows.append(row)
        if isinstance(row, ProviderRequestRow):
            request_ids[row.id] = StoredProviderRequest(
                id=row.id,
                provider_key=row.provider_key,
                dataset_key=row.dataset_key,
                request_key=row.request_key,
                request_params=dict(row.request_params or {}),
                requested_by_run_id=row.requested_by_run_id,
                status=row.status,
            )
        # ProviderAttemptRow / RawProviderBatchRow don't need a
        # in-memory mirror for these tests.

    session.add.side_effect = _add
    return session


def _make_session_factory(session: MagicMock) -> MagicMock:
    return MagicMock(name="SessionProvider", return_value=session)


class EtfInstrumentsRawAssetTest(unittest.TestCase):
    """``etf_instruments_raw`` writes raw.* tables via the real repository code path."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()
        self._as_of = date(2026, 7, 31)
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._records_payload = _serialize_records(
            tuple(self._provider.list_instruments())
        )
        self._uow_factory = _build_uow_factory(
            self._session,
            request_lookup=lambda **_: None,
            attempt_list=_make_attempt_list([]),
            upsert_records=[],
        )

    def test_success_path_persists_three_layers_and_records_sidecar(self) -> None:
        result = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(result.record_count, len(self._provider.list_instruments()))
        self.assertIsNotNone(result.batch_id)

        rows = self._session.added_rows
        request_rows = [r for r in rows if isinstance(r, ProviderRequestRow)]
        attempt_rows = [r for r in rows if isinstance(r, ProviderAttemptRow)]
        batch_rows = [r for r in rows if isinstance(r, RawProviderBatchRow)]

        self.assertEqual(len(request_rows), 1, "exactly one provider_requests row")
        self.assertEqual(len(attempt_rows), 1, "exactly one provider_attempts row")
        self.assertEqual(len(batch_rows), 1, "exactly one provider_batches row")

        request_row = request_rows[0]
        self.assertEqual(request_row.provider_key, "fixture_dev")
        self.assertEqual(request_row.dataset_key, "instruments")
        self.assertEqual(
            request_row.request_key, f"instruments-{self._as_of.isoformat()}"
        )
        self.assertEqual(request_row.status, "pending")
        self.assertEqual(request_row.request_params, {"as_of": self._as_of.isoformat()})

        attempt_row = attempt_rows[0]
        self.assertEqual(attempt_row.provider_request_id, request_row.id)
        self.assertEqual(attempt_row.attempt_no, 1)
        self.assertEqual(attempt_row.status, "succeeded")
        # The attempt carries the records sidecar so the downstream
        # core asset can read it back without re-calling the Provider.
        self.assertEqual(
            attempt_row.response_payload_json, self._records_payload
        )
        self.assertIsNone(attempt_row.error_stage)
        self.assertIsNone(attempt_row.error_code)

        batch_row = batch_rows[0]
        self.assertEqual(batch_row.provider_request_id, request_row.id)
        self.assertEqual(batch_row.provider_attempt_id, attempt_row.id)
        self.assertEqual(batch_row.provider_key, "fixture_dev")
        self.assertEqual(batch_row.dataset_key, "instruments")
        self.assertEqual(
            batch_row.record_count, len(self._provider.list_instruments())
        )
        self.assertEqual(batch_row.status, "succeeded")
        self.assertEqual(batch_row.warnings, [])

        # The UoW committed exactly once and closed the session.
        self._session.commit.assert_called_once_with()
        self._session.close.assert_called_once_with()

    def test_failure_path_persists_no_batch(self) -> None:
        provider = FixtureDevInstrumentProvider(simulate_failure=True)
        result = write_etf_instruments_raw(
            provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertIsNone(result.batch_id)
        self.assertEqual(result.record_count, 0)

        rows = self._session.added_rows
        request_rows = [r for r in rows if isinstance(r, ProviderRequestRow)]
        attempt_rows = [r for r in rows if isinstance(r, ProviderAttemptRow)]
        batch_rows = [r for r in rows if isinstance(r, RawProviderBatchRow)]

        self.assertEqual(len(request_rows), 1)
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(
            len(batch_rows),
            0,
            "failed attempt must not produce a provider_batches row",
        )

        attempt_row = attempt_rows[0]
        self.assertEqual(attempt_row.status, "failed")
        self.assertEqual(attempt_row.error_stage, "provider")
        self.assertEqual(attempt_row.error_code, "simulated_failure")
        self.assertTrue(attempt_row.error_message)
        # Failed attempts carry no SHA-256 — the
        # ``ck_provider_attempts_succeeded_has_hash`` CHECK constraint
        # requires the hash only on success.
        self.assertIsNone(attempt_row.response_payload_sha256)
        self.assertIsNone(attempt_row.response_payload_json)

    def test_idempotent_rerun_creates_fresh_request_via_uow(self) -> None:
        """The asset opens a fresh UoW per run; each run gets its own request UUID."""

        first = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        self._session.added_rows.clear()
        second = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertNotEqual(first.attempt_id, second.attempt_id)


class EtfInstrumentsAssetTest(unittest.TestCase):
    """``etf_instruments`` reads raw.* and upserts into core.instruments."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()
        self._as_of = date(2026, 7, 31)
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._records_payload = _serialize_records(
            tuple(self._provider.list_instruments())
        )
        self._stored_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._stored_request_id,
            provider_key="fixture_dev",
            dataset_key="instruments",
            request_key=f"instruments-{self._as_of.isoformat()}",
            request_params={"as_of": self._as_of.isoformat()},
            status="succeeded",
        )
        self._stored_attempt = StoredProviderAttempt(
            id=uuid4(),
            provider_request_id=self._stored_request_id,
            attempt_no=1,
            started_at=datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 31, 8, 0, 1, tzinfo=UTC),
            status="succeeded",
            response_payload_sha256="abc",
            response_payload_json=self._records_payload,
        )
        self._upsert_calls: list[list[Instrument]] = []
        self._uow_factory = _build_uow_factory(
            self._session,
            request_lookup=lambda **_: self._stored_request,
            attempt_list=_make_attempt_list([self._stored_attempt]),
            upsert_records=self._upsert_calls,
        )

    def test_upsert_deserializes_records_from_attempt_sidecar(self) -> None:
        count = upsert_etf_instruments(
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(count, len(self._provider.list_instruments()))
        self.assertEqual(len(self._upsert_calls), 1)
        instruments = self._upsert_calls[0]
        symbols = [item.symbol for item in instruments]
        self.assertEqual(symbols[0], "510300")
        self.assertEqual(symbols[-1], "518880")
        for instrument in instruments:
            self.assertEqual(instrument.instrument_type, InstrumentType.ETF)
            self.assertEqual(instrument.status, InstrumentStatus.ACTIVE)
            self.assertIsNone(instrument.instrument_id)

    def test_upsert_is_idempotent_across_runs(self) -> None:
        """Re-running with the same persisted state upserts the same records again."""

        upsert_etf_instruments(
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        first_call = list(self._upsert_calls[0])
        upsert_etf_instruments(
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        second_call = list(self._upsert_calls[1])

        self.assertEqual(len(first_call), len(second_call))
        for a, b in zip(first_call, second_call, strict=True):
            self.assertEqual(a.symbol, b.symbol)
            self.assertEqual(a.exchange, b.exchange)
            self.assertEqual(a.name, b.name)

    def test_upsert_raises_when_no_request_persisted(self) -> None:
        empty_factory = _build_uow_factory(
            self._session,
            request_lookup=lambda **_: None,
            attempt_list=_make_attempt_list([]),
            upsert_records=[],
        )
        with self.assertRaises(LookupError):
            upsert_etf_instruments(
                self._factory,
                as_of=self._as_of,
                unit_of_work_factory=empty_factory,
            )

    def test_upsert_raises_when_attempt_failed(self) -> None:
        failed_attempt = StoredProviderAttempt(
            id=uuid4(),
            provider_request_id=self._stored_request_id,
            attempt_no=1,
            started_at=datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 31, 8, 0, 1, tzinfo=UTC),
            status="failed",
            error_stage="provider",
            error_code="simulated_failure",
        )
        failure_factory = _build_uow_factory(
            self._session,
            request_lookup=lambda **_: self._stored_request,
            attempt_list=_make_attempt_list([failed_attempt]),
            upsert_records=[],
        )
        with self.assertRaises(LookupError):
            upsert_etf_instruments(
                self._factory,
                as_of=self._as_of,
                unit_of_work_factory=failure_factory,
            )


if __name__ == "__main__":
    unittest.main()
