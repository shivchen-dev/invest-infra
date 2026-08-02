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

import ast
import inspect
import json
import unittest
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
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
    NewProviderRequest,
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

    ``request_log`` is shared across every UoW instance the factory
    hands out for a given session so that
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` —
    invoked by the raw asset's write path — honours the natural
    ``uq_provider_requests_logical_key`` constraint at the fake
    layer: a second call with the same
    ``(provider_key, dataset_key, request_key)`` returns the row
    inserted by the first call instead of producing a duplicate.
    """

    def __init__(
        self,
        session: MagicMock,
        *,
        request_log: list[ProviderRequestRow],
        request_lookup: Any,
        attempt_list: Any,
        upsert_records: list[list[Instrument]] | None = None,
    ) -> None:
        self._session = session
        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)
        self._request_log = request_log
        self._request_lookup = request_lookup
        self._attempt_list = attempt_list
        self._upsert_calls = upsert_records if upsert_records is not None else []

        # Wire the read paths to the pre-seeded callbacks.
        self._provider_requests.get_by_logical_key = MagicMock(  # type: ignore[method-assign]
            side_effect=request_lookup
        )
        # Override the idempotent write entry point so the fake
        # emulates the database's natural unique constraint on the
        # logical key; the raw asset relies on this for rerun safety.
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._instruments.upsert_many = MagicMock(  # type: ignore[method-assign]
            side_effect=self._record_upsert_call
        )

    def _list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[StoredProviderAttempt]:
        """Return attempts the fake has actually persisted for ``request_id``.

        Mirrors :meth:`SqlAlchemyProviderAttemptRepository.list_by_request`
        against the in-memory ``session.added_rows`` so the raw write
        path's rerun attempt-numbering logic (max existing
        ``attempt_no`` + 1) sees the attempts the previous run
        inserted. Falls back to the pre-seeded ``attempt_list`` callback
        when no attempts have been written to the fake session yet —
        the read-path tests use that callback to project a successful
        attempt the upsert asset should pick up.
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
        if matched:
            projected = [
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
                for row in matched
            ]
            return projected[offset : offset + limit]
        return self._attempt_list(
            request_id, limit=limit, offset=offset
        )

    def _get_or_create(self, request: NewProviderRequest) -> StoredProviderRequest:
        for row in self._request_log:
            if (
                row.provider_key == request.provider_key
                and row.dataset_key == request.dataset_key
                and row.request_key == request.request_key
            ):
                return _row_to_stored_request_from_log(row)
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
        return _row_to_stored_request_from_log(new_row)

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
    request_log: list[ProviderRequestRow] | None = None,
) -> Any:
    # Shared across every UoW the factory creates for this session so
    # ``get_or_create`` sees prior insertions on later runs.
    log = request_log if request_log is not None else []

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(
            session,
            request_log=log,
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


def _row_to_stored_request_from_log(
    row: ProviderRequestRow,
) -> StoredProviderRequest:
    """Project a tracked ``ProviderRequestRow`` back to its domain view."""

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
        self.assertEqual(request_row.dataset_key, "etf_instruments")
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
        self.assertEqual(batch_row.dataset_key, "etf_instruments")
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

    def test_idempotent_rerun_reuses_logical_request_via_uow(self) -> None:
        """A rerun reuses the existing ``raw.provider_requests`` row and
        records a fresh attempt + batch instead of violating the
        ``uq_provider_requests_logical_key`` constraint.
        """

        first = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        second = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )
        third = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
            unit_of_work_factory=self._uow_factory,
        )

        # The logical request is reused — same UUID, only one row in
        # ``raw.provider_requests`` across all three runs.
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.request_id, third.request_id)
        rows = self._session.added_rows
        request_rows = [r for r in rows if isinstance(r, ProviderRequestRow)]
        self.assertEqual(
            len(request_rows),
            1,
            "get_or_create must not re-insert the existing request row",
        )

        # The audit trail still grows — a fresh attempt + batch is
        # recorded for every rerun, with ``attempt_no`` derived from
        # the existing attempts so the ``uq_provider_attempts_request_attempt_no``
        # constraint is satisfied across reruns (fixture providers keep
        # returning ``attempt_number=1``).
        self.assertNotEqual(first.attempt_id, second.attempt_id)
        self.assertNotEqual(second.attempt_id, third.attempt_id)
        attempt_rows = [r for r in rows if isinstance(r, ProviderAttemptRow)]
        batch_rows = [r for r in rows if isinstance(r, RawProviderBatchRow)]
        self.assertEqual(len(attempt_rows), 3)
        self.assertEqual(len(batch_rows), 3)
        attempt_nos = sorted(row.attempt_no for row in attempt_rows)
        self.assertEqual(attempt_nos, [1, 2, 3])
        for row in attempt_rows:
            self.assertEqual(row.provider_request_id, first.request_id)
        for row in batch_rows:
            self.assertEqual(row.provider_request_id, first.request_id)

    def test_first_run_preserves_provider_attempt_number(self) -> None:
        """First-run ``attempt_no`` honours the value the provider returns.

        Guards against the rerun-fix accidentally forcing every attempt
        to ``max(existing)+1``: a fresh logical request has no existing
        attempts, so ``attempt.attempt_number`` (currently ``1`` for the
        fixture_dev adapter) must still flow through.
        """

        result = write_etf_instruments_raw(
            self._provider,
            self._factory,
            as_of=self._as_of,
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
            dataset_key="etf_instruments",
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


class EtfInstrumentsFormalDatasetKeyRegressionTest(unittest.TestCase):
    """Regression: ``etf_instruments`` must look up by the formal ``"etf_instruments"`` key.

    Before this fix :func:`invest_pipeline.etf_instruments.upsert_etf_instruments`
    and the downstream ``etf_instruments`` Dagster asset defaulted to
    ``dataset_key="instruments"`` while the CifangQuant adapter (and
    every future real provider) stamps the persisted request with the
    formal ``"etf_instruments"`` key. The mismatch caused the formal
    CifangQuant path to silently skip every ``core.instruments``
    upsert — the candidate-pool downstream of it kept reading the
    stale fixture rows instead of the 862-row real master data.

    The tests below pin the unified formal key end-to-end:

    * :func:`upsert_etf_instruments`' default ``dataset_key`` is
      ``"etf_instruments"`` (no caller has to pass it explicitly).
    * A CifangQuant-shaped provider round-trip
      (``write_etf_instruments_raw`` → ``upsert_etf_instruments``)
      flows through the same logical key the asset's
      ``provider_requests.get_by_logical_key`` lookup uses.
    * The :func:`invest_pipeline.assets.etf_instruments` source body
      no longer hard-codes ``dataset_key="instruments"`` — the AST
      check guards against the legacy string sneaking back in.
    """

    def test_default_dataset_key_is_formal_etf_instruments(self) -> None:
        import inspect

        default = inspect.signature(upsert_etf_instruments).parameters[
            "dataset_key"
        ].default
        self.assertEqual(default, "etf_instruments")

    def test_upsert_lookup_uses_formal_etf_instruments_for_cifangquant(self) -> None:
        """A CifangQuant run must be found by the formal ``"etf_instruments"`` key.

        The fake ``request_lookup`` callback is parameterised by the
        caller-supplied kwargs so we can prove the service asks for
        ``dataset_key="etf_instruments"`` (and not the legacy
        ``"instruments"`` string). Returning the persisted request
        only when the lookup uses the formal key is what closes the
        production bug.
        """

        captured: dict[str, Any] = {}
        provider_key = "cifangquant"
        request_key = f"instruments-{self._as_of().isoformat()}"
        stored_attempt = StoredProviderAttempt(
            id=uuid4(),
            provider_request_id=uuid4(),
            attempt_no=1,
            started_at=datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 31, 8, 0, 1, tzinfo=UTC),
            status="succeeded",
            response_payload_sha256="abc",
            response_payload_json=self._records_payload(),
        )

        def _lookup(**kwargs: Any) -> StoredProviderRequest | None:
            captured["provider_key"] = kwargs.get("provider_key")
            captured["dataset_key"] = kwargs.get("dataset_key")
            captured["request_key"] = kwargs.get("request_key")
            if (
                kwargs.get("provider_key") == provider_key
                and kwargs.get("dataset_key") == "etf_instruments"
                and kwargs.get("request_key") == request_key
            ):
                return StoredProviderRequest(
                    id=uuid4(),
                    provider_key=provider_key,
                    dataset_key="etf_instruments",
                    request_key=request_key,
                    request_params={"as_of": self._as_of().isoformat()},
                    status="succeeded",
                )
            return None

        session = _build_session()
        factory = _make_session_factory(session)
        upsert_calls: list[list[Instrument]] = []
        uow_factory = _build_uow_factory(
            session,
            request_lookup=_lookup,
            attempt_list=_make_attempt_list([stored_attempt]),
            upsert_records=upsert_calls,
        )

        count = upsert_etf_instruments(
            factory,
            as_of=self._as_of(),
            provider_key=provider_key,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(captured["dataset_key"], "etf_instruments")
        self.assertEqual(captured["provider_key"], provider_key)
        self.assertEqual(captured["request_key"], request_key)
        self.assertEqual(count, len(self._provider().list_instruments()))
        self.assertEqual(len(upsert_calls), 1)
        symbols = [item.symbol for item in upsert_calls[0]]
        self.assertIn("510300", symbols)

    def test_upsert_misses_legacy_instruments_key_for_cifangquant(self) -> None:
        """Pin: a stale ``dataset_key="instruments"`` lookup MUST NOT find the request.

        The production bug surfaced because the asset looked up the
        request with the legacy ``"instruments"`` key while real
        providers stamp ``"etf_instruments"``. This test guards the
        inverse: even if a future refactor regresses the asset to
        ``"instruments"``, the fake's ``request_lookup`` will return
        ``None`` (mimicking the real DB) and the upsert raises
        :class:`LookupError` rather than silently upserting zero rows.
        """

        provider_key = "cifangquant"
        request_key = f"instruments-{self._as_of().isoformat()}"

        def _lookup(**kwargs: Any) -> StoredProviderRequest | None:
            if kwargs.get("dataset_key") != "etf_instruments":
                return None
            return StoredProviderRequest(
                id=uuid4(),
                provider_key=provider_key,
                dataset_key="etf_instruments",
                request_key=request_key,
                request_params={"as_of": self._as_of().isoformat()},
                status="succeeded",
            )

        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _build_uow_factory(
            session,
            request_lookup=_lookup,
            attempt_list=_make_attempt_list([]),
            upsert_records=[],
        )

        with self.assertRaises(LookupError):
            upsert_etf_instruments(
                factory,
                as_of=self._as_of(),
                provider_key=provider_key,
                dataset_key="instruments",
                unit_of_work_factory=uow_factory,
            )

    def test_cifangquant_shaped_provider_round_trip_into_core_instruments(
        self,
    ) -> None:
        """End-to-end: a CifangQuant-shaped provider produces core.instruments upserts.

        The stub provider mirrors
        :class:`invest_pipeline.adapters.cifang.adapter.CifangQuantInstrumentProvider`
        by stamping ``dataset_key="etf_instruments"`` and
        ``provider_key="cifangquant"``. The test runs
        :func:`write_etf_instruments_raw` against the fake UoW and then
        :func:`upsert_etf_instruments` with no caller-supplied
        ``dataset_key`` — the service's default
        ``dataset_key="etf_instruments"`` must find the persisted
        request and forward the records into
        :meth:`SqlAlchemyInstrumentRepository.upsert_many`.
        """

        provider = _CifangQuantShapedProvider(
            instruments=tuple(self._provider().list_instruments())
        )
        session = _build_session()
        factory = _make_session_factory(session)

        raw_result = write_etf_instruments_raw(
            provider,
            factory,
            as_of=self._as_of(),
            unit_of_work_factory=_build_uow_factory(
                session,
                request_lookup=lambda **_: None,
                attempt_list=_make_attempt_list([]),
                upsert_records=[],
            ),
        )
        self.assertEqual(raw_result.request_status, "succeeded")
        self.assertEqual(raw_result.attempt_status, "succeeded")
        self.assertEqual(
            raw_result.record_count,
            len(self._provider().list_instruments()),
        )

        # The persisted request must carry the formal key the asset
        # looks up downstream.
        request_rows = [
            row
            for row in session.added_rows
            if isinstance(row, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)
        persisted = request_rows[0]
        self.assertEqual(persisted.provider_key, "cifangquant")
        self.assertEqual(persisted.dataset_key, "etf_instruments")

        upsert_calls: list[list[Instrument]] = []
        uow_factory = _build_uow_factory(
            session,
            request_lookup=_lookup_matching_persisted(session),
            attempt_list=_attempt_list_for_persisted(session),
            upsert_records=upsert_calls,
        )

        count = upsert_etf_instruments(
            factory,
            as_of=self._as_of(),
            provider_key="cifangquant",
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(count, len(self._provider().list_instruments()))
        self.assertEqual(len(upsert_calls), 1)
        self.assertEqual(
            sorted(item.symbol for item in upsert_calls[0]),
            sorted(item.symbol for item in self._provider().list_instruments()),
        )

    def test_etf_instruments_asset_body_uses_formal_etf_instruments(self) -> None:
        """Source-level guard: the asset must not hard-code the legacy ``"instruments"`` key.

        Without this check a future refactor could quietly reintroduce
        the bug by changing the asset body back to
        ``dataset_key="instruments"``. Both the formal string must be
        present (so the lookup uses it) and the legacy string must be
        absent from the lookup kwargs.
        """

        from invest_pipeline import assets

        src_path = Path(inspect.getsourcefile(assets) or "").resolve()
        source_text = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        body_segment = ""
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "etf_instruments":
                body_segment = ast.get_source_segment(source_text, node) or ""
                break
        self.assertTrue(body_segment, "etf_instruments asset source must be parseable")
        self.assertIn('dataset_key="etf_instruments"', body_segment)
        self.assertNotIn('dataset_key="instruments"', body_segment)

    # -- helpers --------------------------------------------------------

    def _as_of(self) -> date:
        return date(2026, 7, 31)

    def _provider(self) -> FixtureDevInstrumentProvider:
        return FixtureDevInstrumentProvider()

    def _records_payload(self) -> str:
        return _serialize_records(tuple(self._provider().list_instruments()))


def _lookup_matching_persisted(
    session: MagicMock,
) -> Any:
    """Return a ``request_lookup`` callback that matches the just-persisted row.

    Walks ``session.added_rows`` to find the unique
    :class:`ProviderRequestRow` the raw write produced and returns a
    :class:`StoredProviderRequest` projection. The callback only
    matches when the caller passes the same logical
    ``(provider_key, dataset_key, request_key)`` so a future refactor
    that passes a wrong key surfaces as a :class:`LookupError`.
    """

    def _factory(**kwargs: Any) -> StoredProviderRequest | None:
        for row in session.added_rows:
            if not isinstance(row, ProviderRequestRow):
                continue
            if (
                row.provider_key == kwargs.get("provider_key")
                and row.dataset_key == kwargs.get("dataset_key")
                and row.request_key == kwargs.get("request_key")
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
        return None

    return _factory


def _attempt_list_for_persisted(session: MagicMock) -> Any:
    """Return an ``attempt_list`` callback that surfaces the persisted attempt."""

    def _factory(
        request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[StoredProviderAttempt]:
        matched = sorted(
            (
                row
                for row in session.added_rows
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

    return _factory


class _CifangQuantShapedProvider:
    """Minimal CifangQuant-shaped stub for end-to-end round-trip testing.

    Mirrors :class:`invest_pipeline.adapters.cifang.adapter.CifangQuantInstrumentProvider`'s
    evidence-tuple shape but stamps ``provider_key="cifangquant"`` /
    ``dataset_key="etf_instruments"`` so the test exercises the formal
    ``raw.*`` key without booting the real provider (which is gated on
    :class:`CifangSettings.enabled`).
    """

    def __init__(self, *, instruments: tuple[Instrument, ...]) -> None:
        self._instruments = instruments
        self._raw_payload_hash = sha256(
            json.dumps([i.symbol for i in instruments]).encode("utf-8")
        ).hexdigest()

    @property
    def provider_key(self) -> str:
        return "cifangquant"

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[Any, Any, Any]:
        started_at = datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC)
        finished_at = datetime(2026, 7, 31, 8, 0, 1, tzinfo=UTC)
        attempt_id = uuid4()
        request = MagicMock(name="ProviderRequest")
        request.provider_key = "cifangquant"
        request.dataset_key = "etf_instruments"
        request.request_key = f"instruments-{as_of.isoformat()}"
        request.params = {"as_of": as_of.isoformat()}
        request.created_at = started_at
        attempt = MagicMock(name="ProviderAttempt")
        attempt.attempt_number = 1
        attempt.status = ProviderAttemptStatus.SUCCEEDED
        attempt.started_at = started_at
        attempt.finished_at = finished_at
        attempt.error_stage = None
        attempt.error_code = None
        attempt.error_message = None
        batch = MagicMock(name="ProviderBatch")
        batch.attempt_id = attempt_id
        batch.records = self._instruments
        batch.raw_payload_hash = self._raw_payload_hash
        batch.status = ProviderBatchStatus.SUCCEEDED
        batch.warnings = ()
        return request, attempt, batch


if __name__ == "__main__":
    unittest.main()
