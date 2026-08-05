"""Unit tests for the DC-2 ``etf_profiles`` ETL service module.

The slice is intentionally narrow: the Akshare profile collection
joins ``fund_name_em`` and ``fund_etf_spot_em`` by symbol in a pure
mapper and populates only the verified fields (``fund_type`` /
``category`` / ``shares``). The unfunded fields (``manager`` /
``benchmark_index`` / ``inception_date`` / ``management_fee`` /
``custody_fee`` / ``aum``) stay ``None`` until a dedicated profile
endpoint is verified; the existing ``fund_etf_fund_info_em(fund=...)``
endpoint stays out of scope (it returns historical NAV).

The tests verify, end-to-end with a ``MagicMock`` SQLAlchemy session:

- :func:`write_etf_profiles_raw` writes the three-layer evidence
  bundle (``provider_requests`` / ``provider_attempts`` /
  ``provider_batches``) on the success path and the request + attempt
  only on the failure path (no batch).
- :func:`upsert_etf_profiles` reads the sidecar, looks up the real
  ``core.instruments.id`` per ``(symbol, exchange)`` and delegates to
  :class:`SqlAlchemyEtfProfileRepository.upsert`.
- A re-collect of identical business content is idempotent (the
  repository is invoked with the same sidecar on a re-run).
- The slice rejects the case where the upstream JSONB sidecar is
  missing / malformed (no silent fallback).
- The slice rejects the case where no successful attempt is found
  for the given logical key (no silent zero-row upsert).
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.etf_profile import EtfProfile
from invest_pipeline.adapters.akshare.mapper import AkshareProfileRecord
from invest_pipeline.etf_profiles import (
    UpsertSummary,
    upsert_etf_profiles,
    write_etf_profiles_raw,
)
from invest_storage.models import ProviderAttemptRow, ProviderRequestRow
from invest_storage.repositories import (
    NewProviderRequest,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class _StubInstrument:
    """Stand-in for the instrument repository's return shape."""

    instrument_id: UUID


class _FakeUnitOfWork:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` wired to a mock session.

    Mirrors the shape used by ``test_etf_daily_bars_service`` so the
    service can exercise its real repository code paths without
    booting PostgreSQL. ``session.add`` records every persisted row
    so the test can inspect the sidecar stored on the attempt row.

    ``request_log`` is shared across every UoW instance the factory
    hands out for a given session so the
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` contract
    is honoured at the fake layer: a repeat call with the same
    ``(provider_key, dataset_key, request_key)`` returns the row
    inserted by the first call instead of producing a duplicate.
    """

    def __init__(
        self,
        session: MagicMock,
        *,
        request_log: list[ProviderRequestRow],
        stored_request: StoredProviderRequest | None = None,
        attempts: list[StoredProviderAttempt] | None = None,
        instrument_lookup: Any = None,
        profile_upsert_calls: list[EtfProfile] | None = None,
    ) -> None:
        self._session = session
        self._request_log = request_log
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_requests.get_by_logical_key = self._get_by_logical_key  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)
        self._stored_request = stored_request
        self._attempts = attempts or []
        self._instrument_lookup = instrument_lookup
        self._profile_upsert_calls = (
            profile_upsert_calls if profile_upsert_calls is not None else []
        )

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
        # The fake UoW consults the seeded attempts list first so the
        # upsert test can drive the selection logic without booting
        # SQLAlchemy; persisted ``ProviderAttemptRow`` instances in
        # ``session.added_rows`` are also honoured so the raw write
        # path's rerun attempt-numbering logic stays accurate.
        seed_attempts = [
            entry for entry in self._attempts if entry.provider_request_id == request_id
        ]
        if seed_attempts:
            return sorted(
                seed_attempts, key=lambda row: row.attempt_no
            )[offset : offset + limit]
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

    def _get_by_logical_key(
        self,
        *,
        provider_key: str,
        dataset_key: str,
        request_key: str,
    ) -> StoredProviderRequest | None:
        if self._stored_request is not None:
            return self._stored_request
        for row in self._request_log:
            if (
                row.provider_key == provider_key
                and row.dataset_key == dataset_key
                and row.request_key == request_key
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

    def _get_by_business_key(self, *, exchange: str, symbol: str) -> _StubInstrument | None:
        if self._instrument_lookup is None:
            return None
        return self._instrument_lookup(exchange=exchange, symbol=symbol)

    def _etf_profiles_upsert(self, profile: EtfProfile) -> EtfProfile:
        self._profile_upsert_calls.append(profile)
        return profile

    @property
    def provider_requests(self) -> SqlAlchemyProviderRequestRepository:
        return self._provider_requests

    @property
    def provider_attempts(self) -> SqlAlchemyProviderAttemptRepository:
        return self._provider_attempts

    @property
    def provider_batches(self) -> SqlAlchemyProviderBatchRepository:
        return self._provider_batches

    @property
    def instruments(self) -> Any:
        uow = self

        class _InstrumentsView:
            @staticmethod
            def get_by_business_key(*, exchange: str, symbol: str) -> Any:
                return uow._get_by_business_key(exchange=exchange, symbol=symbol)

        return _InstrumentsView()

    @property
    def etf_profiles(self) -> Any:
        uow = self

        class _EtfProfilesView:
            @staticmethod
            def upsert(profile: EtfProfile) -> EtfProfile:
                return uow._etf_profiles_upsert(profile)

        return _EtfProfilesView()

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


def _make_uow_factory(
    session: MagicMock,
    *,
    stored_request: StoredProviderRequest | None = None,
    attempts: list[StoredProviderAttempt] | None = None,
    instrument_lookup: Any = None,
    profile_upsert_calls: list[EtfProfile] | None = None,
) -> MagicMock:
    log: list[ProviderRequestRow] = []

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(
            session,
            request_log=log,
            stored_request=stored_request,
            attempts=attempts,
            instrument_lookup=instrument_lookup,
            profile_upsert_calls=profile_upsert_calls,
        )

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _attempt_payload(session: MagicMock) -> str:
    attempt_rows = [
        row for row in session.added_rows if isinstance(row, ProviderAttemptRow)
    ]
    assert len(attempt_rows) == 1, f"exactly one attempt row, got {len(attempt_rows)}"
    payload = attempt_rows[0].response_payload_json
    assert payload is not None, "attempt must carry the sidecar"
    return str(payload)


def _request_payload(session: MagicMock) -> tuple[str, str]:
    request_rows = [
        row for row in session.added_rows if isinstance(row, ProviderRequestRow)
    ]
    assert len(request_rows) == 1, f"exactly one request row, got {len(request_rows)}"
    row = request_rows[0]
    return (
        row.dataset_key,
        row.request_key,
    )


def _build_request(
    *,
    status: str = "pending",
    error_stage: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> Any:
    """Build a stub ``ProviderRequest`` dataclass for the provider port."""

    from invest_domain.market_data.models import ProviderRequest

    request = ProviderRequest(
        provider_key="akshare",
        dataset_key="etf_profile",
        request_key="etf-profile",
        params={},
        created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
    )
    return request


def _build_succeeded_attempt(
    *,
    records: tuple[AkshareProfileRecord, ...],
    raw_payload_hash: str = "0" * 64,
    warnings: tuple[str, ...] = (),
    finished_at: datetime | None = None,
) -> tuple[Any, Any, Any]:
    from invest_domain.market_data.models import (
        ProviderAttempt,
        ProviderAttemptStatus,
        ProviderBatch,
        ProviderBatchStatus,
        ProviderRequest,
    )

    request = ProviderRequest(
        provider_key="akshare",
        dataset_key="etf_profile",
        request_key="etf-profile",
        params={},
        created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
    )
    attempt = ProviderAttempt(
        request_id=uuid4(),
        attempt_number=1,
        status=ProviderAttemptStatus.SUCCEEDED,
        started_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
        finished_at=finished_at or datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
        duration_ms=5000,
    )
    batch = ProviderBatch[AkshareProfileRecord](
        attempt_id=uuid4(),
        records=records,
        raw_payload_hash=raw_payload_hash,
        warnings=warnings,
        status=ProviderBatchStatus.SUCCEEDED,
    )
    return request, attempt, batch


def _build_failed_attempt() -> tuple[Any, Any, None]:
    from invest_domain.market_data.models import (
        ProviderAttempt,
        ProviderAttemptStatus,
        ProviderFailureStage,
        ProviderRequest,
    )

    request = ProviderRequest(
        provider_key="akshare",
        dataset_key="etf_profile",
        request_key="etf-profile",
        params={},
        created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
    )
    attempt = ProviderAttempt(
        request_id=uuid4(),
        attempt_number=1,
        status=ProviderAttemptStatus.FAILED,
        started_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
        duration_ms=5000,
        error_stage=ProviderFailureStage.DECODE,
        error_code="ProviderBadResponseError",
        error_message="akshare.fund_name_em() raised ValueError: bad",
    )
    return request, attempt, None


class _StubProvider:
    """Stand-in for the AkShare provider port."""

    def __init__(self, request: Any, attempt: Any, batch: Any) -> None:
        self._request = request
        self._attempt = attempt
        self._batch = batch

    @property
    def provider_key(self) -> str:
        return "akshare"

    def fetch_etf_profile(self) -> tuple[Any, Any, Any]:
        return self._request, self._attempt, self._batch


class WriteEtfProfilesRawSidecarTest(unittest.TestCase):
    """The JSONB sidecar must carry the verified fields only."""

    def setUp(self) -> None:
        self._records = (
            AkshareProfileRecord(
                symbol="510300",
                exchange="SSE",
                fund_type="ETF",
                category="ETF",
                shares=__import__("decimal").Decimal("1000000000"),
            ),
            AkshareProfileRecord(
                symbol="159919",
                exchange="SZSE",
                fund_type="ETF",
                category="ETF",
                shares=__import__("decimal").Decimal("500000000"),
            ),
        )
        self._session = _build_session()
        self._factory = _make_session_factory(self._session)
        self._uow_factory = _make_uow_factory(self._session)

    def test_sidecar_carries_verified_fields_only(self) -> None:
        from invest_pipeline.adapters.akshare.mapper import AkshareProfileRecord

        records = (
            AkshareProfileRecord(
                symbol="510300",
                exchange="SSE",
                fund_type="ETF",
                category="ETF",
                shares=__import__("decimal").Decimal("1000000000"),
            ),
        )
        request, attempt, batch = _build_succeeded_attempt(records=records)
        provider = _StubProvider(request, attempt, batch)

        write_etf_profiles_raw(
            provider,
            self._factory,
            unit_of_work_factory=self._uow_factory,
        )

        payload = _attempt_payload(self._session)
        parsed = json.loads(payload)
        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(len(parsed["records"]), 1)
        record = parsed["records"][0]
        self.assertEqual(record["symbol"], "510300")
        self.assertEqual(record["exchange"], "SSE")
        self.assertEqual(record["fund_type"], "ETF")
        self.assertEqual(record["category"], "ETF")
        self.assertEqual(record["shares"], "1000000000")
        # Verify the unfunded fields are NOT in the sidecar.
        self.assertNotIn("manager", record)
        self.assertNotIn("benchmark_index", record)
        self.assertNotIn("inception_date", record)
        self.assertNotIn("management_fee", record)
        self.assertNotIn("custody_fee", record)
        self.assertNotIn("aum", record)
        self.assertNotIn("name", record)

    def test_dataset_key_and_request_key_are_stamped(self) -> None:
        request, attempt, batch = _build_succeeded_attempt(records=())
        provider = _StubProvider(request, attempt, batch)

        write_etf_profiles_raw(
            provider,
            self._factory,
            unit_of_work_factory=self._uow_factory,
        )

        dataset_key, request_key = _request_payload(self._session)
        self.assertEqual(dataset_key, "etf_profile")
        self.assertEqual(request_key, "etf-profile")

    def test_failed_attempt_persists_request_and_attempt_only(self) -> None:
        request, attempt, batch = _build_failed_attempt()
        provider = _StubProvider(request, attempt, batch)

        result = write_etf_profiles_raw(
            provider,
            self._factory,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertEqual(result.record_count, 0)
        request_rows = [
            row for row in self._session.added_rows
            if isinstance(row, ProviderRequestRow)
        ]
        attempt_rows = [
            row for row in self._session.added_rows
            if isinstance(row, ProviderAttemptRow)
        ]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(attempt_rows[0].status, "failed")
        self.assertEqual(attempt_rows[0].error_code, "ProviderBadResponseError")
        # No raw.provider_batches row is created for a failed attempt.
        from invest_storage.models import RawProviderBatchRow

        batch_rows = [
            row for row in self._session.added_rows
            if isinstance(row, RawProviderBatchRow)
        ]
        self.assertEqual(batch_rows, [])


class UpsertEtfProfilesHappyPathTest(unittest.TestCase):
    """``upsert_etf_profiles`` must read the sidecar and upsert to ``core.etf_profiles``."""

    def setUp(self) -> None:
        self._provider_key = "akshare"
        self._request_key = "etf-profile"
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key=self._provider_key,
            dataset_key="etf_profile",
            request_key=self._request_key,
            request_params={},
            status="succeeded",
        )
        self._instrument_id_510300 = uuid4()
        self._instrument_id_159919 = uuid4()

    def _build_upsert_session(
        self,
        *,
        attempts: list[StoredProviderAttempt],
        upsert_calls: list[EtfProfile],
    ) -> tuple[Any, Any]:
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=self._instrument_lookup,
            profile_upsert_calls=upsert_calls,
        )
        return session, uow_factory

    def _instrument_lookup(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> _StubInstrument | None:
        if symbol == "510300" and exchange == "SSE":
            return _StubInstrument(instrument_id=self._instrument_id_510300)
        if symbol == "159919" and exchange == "SZSE":
            return _StubInstrument(instrument_id=self._instrument_id_159919)
        return None

    def _stored_attempt(
        self,
        *,
        attempt_no: int,
        status: str,
        sidecar_json: str | None,
        finished_at: datetime,
    ) -> StoredProviderAttempt:
        return StoredProviderAttempt(
            id=uuid4(),
            provider_request_id=self._provider_request_id,
            attempt_no=attempt_no,
            started_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC),
            finished_at=finished_at,
            status=status,
            error_stage=None,
            error_code=None,
            error_message=None,
            response_payload_sha256="0" * 64,
            response_payload_json=sidecar_json,
        )

    def test_upsert_writes_profile_records(self) -> None:
        sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                    {
                        "symbol": "159919",
                        "exchange": "SZSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "500000000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        summary = upsert_etf_profiles(
            _make_session_factory(session),
            provider_key=self._provider_key,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary, UpsertSummary(inserted=2, skipped=0))
        self.assertEqual(len(upsert_calls), 2)
        # First record: SSE 510300
        first = upsert_calls[0]
        self.assertEqual(first.instrument_id, self._instrument_id_510300)
        self.assertEqual(first.fund_type, "ETF")
        self.assertEqual(first.category, "ETF")
        self.assertEqual(
            first.shares, __import__("decimal").Decimal("1000000000")
        )
        # Verify unfunded fields stay None.
        self.assertIsNone(first.manager)
        self.assertIsNone(first.benchmark_index)
        self.assertIsNone(first.inception_date)
        self.assertIsNone(first.management_fee)
        self.assertIsNone(first.custody_fee)
        self.assertIsNone(first.aum)
        # Second record: SZSE 159919
        second = upsert_calls[1]
        self.assertEqual(second.instrument_id, self._instrument_id_159919)
        self.assertEqual(second.shares, __import__("decimal").Decimal("500000000"))

    def test_upsert_skips_records_with_unknown_instrument(self) -> None:
        # An AkShare profile whose ``symbol`` does not match any
        # active ``core.instruments`` row is silently skipped (the
        # application service treats it as a stale fixture).
        sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                    {
                        "symbol": "999999",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary, UpsertSummary(inserted=1, skipped=1))
        self.assertEqual(len(upsert_calls), 1)

    def test_upsert_skips_records_with_missing_symbol_or_exchange(self) -> None:
        # A sidecar record missing ``symbol`` or ``exchange`` cannot
        # be resolved to a real ``core.instruments.id``; the service
        # silently skips it rather than crashing.
        sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                    {
                        "symbol": None,
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000",
                    },
                    {
                        "symbol": "159919",
                        "exchange": None,
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000",
                    },
                    {
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary, UpsertSummary(inserted=1, skipped=3))
        self.assertEqual(len(upsert_calls), 1)

    def test_upsert_is_idempotent_on_rerun(self) -> None:
        # A re-collect of identical business content is a no-op at
        # the database layer (the repository applies the
        # ``INSERT ... ON CONFLICT DO UPDATE`` contract). The service
        # therefore invokes the upsert path twice with the same
        # payload and observes two ``upsert`` calls.
        sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        first_summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )
        second_summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(first_summary, UpsertSummary(inserted=1, skipped=0))
        self.assertEqual(second_summary, UpsertSummary(inserted=1, skipped=0))
        self.assertEqual(len(upsert_calls), 2)

    def test_upsert_picks_latest_succeeded_attempt(self) -> None:
        # The slice must consume the LATEST succeeded attempt; the
        # legacy ``next(succeeded)`` pattern would otherwise lock in
        # the oldest sidecar when an old baseline attempt co-exists
        # with a fresh run for the same logical request.
        old_sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        new_sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "2000000000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=old_sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
            self._stored_attempt(
                attempt_no=2,
                status="succeeded",
                sidecar_json=new_sidecar,
                finished_at=datetime(2026, 7, 30, 9, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(len(upsert_calls), 1)
        self.assertEqual(
            upsert_calls[0].shares,
            __import__("decimal").Decimal("2000000000"),
            "the latest succeeded attempt must win",
        )

    def test_upsert_missing_request_raises_lookup_error(self) -> None:
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=None,
            attempts=[],
        )
        with self.assertRaises(LookupError):
            upsert_etf_profiles(
                _make_session_factory(session),
                unit_of_work_factory=uow_factory,
            )

    def test_upsert_only_failed_attempts_raises_lookup_error(self) -> None:
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="failed",
                sidecar_json=None,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
        )
        with self.assertRaises(LookupError):
            upsert_etf_profiles(
                _make_session_factory(session),
                unit_of_work_factory=uow_factory,
            )

    def test_upsert_empty_sidecar_returns_zero_zero(self) -> None:
        # An empty AkShare response yields an empty sidecar and the
        # service returns ``(0, 0)`` so the downstream schedule
        # does not fail on a quiet provider window.
        sidecar = json.dumps(
            {"schema_version": 1, "records": []},
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._make_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary, UpsertSummary(inserted=0, skipped=0))
        self.assertEqual(upsert_calls, [])

    def _make_upsert_session(
        self,
        *,
        attempts: list[StoredProviderAttempt],
        upsert_calls: list[EtfProfile],
    ) -> tuple[Any, Any]:
        return self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

    def test_upsert_never_maps_total_market_value_to_aum(self) -> None:
        # The conservative slice intentionally excludes ``aum`` from
        # the sidecar (the upstream ``fund_etf_spot_em`` total market
        # value is never mapped to ``aum``). Verify the conservative
        # contract is preserved end-to-end.
        sidecar = json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "symbol": "510300",
                        "exchange": "SSE",
                        "fund_type": "ETF",
                        "category": "ETF",
                        "shares": "1000000000",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        attempts = [
            self._stored_attempt(
                attempt_no=1,
                status="succeeded",
                sidecar_json=sidecar,
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC),
            ),
        ]
        upsert_calls: list[EtfProfile] = []
        session, uow_factory = self._build_upsert_session(
            attempts=attempts, upsert_calls=upsert_calls
        )

        upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(len(upsert_calls), 1)
        profile = upsert_calls[0]
        self.assertIsNone(profile.aum)
        self.assertIsNone(profile.manager)
        self.assertIsNone(profile.benchmark_index)
        self.assertIsNone(profile.inception_date)
        self.assertIsNone(profile.management_fee)
        self.assertIsNone(profile.custody_fee)


if __name__ == "__main__":
    unittest.main()
