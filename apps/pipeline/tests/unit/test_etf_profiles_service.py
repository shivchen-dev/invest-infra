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
- :func:`upsert_etf_profiles` additionally wires the
  ``map_etf_profile_to_field_evidence`` mapper into the audit pipeline
  so every successful AkShare profile snapshot persists
  :class:`FieldEvidence` rows through ``uow.etf_profile_fields`` with
  the upstream ``source_batch_id``, ``observed_at`` and confidence
  score stamped on every row. The repository's idempotent
  ``ON CONFLICT (content_hash) DO NOTHING`` contract is honoured on
  duplicate runs.
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
from decimal import Decimal
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.etf_profile import EtfProfile
from invest_domain.etf_profile.models import FieldEvidence
from invest_domain.instruments.models import InstrumentId
from invest_pipeline.adapters.akshare.mapper import (
    AkshareProfileMappingResult,
    AkshareProfileRecord,
    map_etf_profile_to_field_evidence,
)
from invest_pipeline.etf_profiles import (
    UpsertSummary,
    upsert_etf_profiles,
    write_etf_profiles_raw,
)
from invest_storage.models import (
    ProviderAttemptRow,
    ProviderRequestRow,
    RawProviderBatchRow,
)
from invest_storage.repositories import (
    NewProviderRequest,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderBatch,
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
        field_evidence_add_calls: list[FieldEvidence] | None = None,
        batches_by_attempt: dict[UUID, list[StoredProviderBatch]] | None = None,
        field_evidence_rows: list[FieldEvidence] | None = None,
    ) -> None:
        self._session = session
        self._request_log = request_log
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_requests.get_by_logical_key = self._get_by_logical_key  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)
        self._provider_batches.list_by_attempt = self._list_batches_by_attempt  # type: ignore[method-assign]
        self._stored_request = stored_request
        self._attempts = attempts or []
        self._instrument_lookup = instrument_lookup
        self._profile_upsert_calls = (
            profile_upsert_calls if profile_upsert_calls is not None else []
        )
        self._field_evidence_add_calls = (
            field_evidence_add_calls if field_evidence_add_calls is not None else []
        )
        self._batches_by_attempt = batches_by_attempt or {}
        self._field_evidence_rows = list(field_evidence_rows or [])

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
            return sorted(seed_attempts, key=lambda row: row.attempt_no)[offset : offset + limit]
        matched = sorted(
            (
                row
                for row in self._session.added_rows
                if isinstance(row, ProviderAttemptRow) and row.provider_request_id == request_id
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

    def _etf_profile_fields_add(self, evidence: FieldEvidence) -> FieldEvidence:
        self._field_evidence_add_calls.append(evidence)
        self._field_evidence_rows.append(evidence)
        return evidence

    def _etf_profile_fields_get_by_instrument(self, instrument_id: UUID) -> list[FieldEvidence]:
        return [
            evidence
            for evidence in self._field_evidence_rows
            if evidence.instrument_id == instrument_id
        ]

    def _list_batches_by_attempt(
        self, attempt_id: UUID, *, limit: int = 10, offset: int = 0
    ) -> list[StoredProviderBatch]:
        seed = list(self._batches_by_attempt.get(attempt_id, []))
        if seed:
            return list(seed[offset : offset + limit])
        matched = sorted(
            (
                row
                for row in self._session.added_rows
                if isinstance(row, RawProviderBatchRow) and row.provider_attempt_id == attempt_id
            ),
            key=lambda row: row.created_at or datetime.min,
            reverse=True,
        )
        return [
            StoredProviderBatch(
                id=row.id,
                provider_request_id=row.provider_request_id,
                provider_attempt_id=row.provider_attempt_id,
                provider_key=row.provider_key,
                dataset_key=row.dataset_key,
                record_count=row.record_count,
                payload_sha256=row.payload_sha256,
                warnings=list(row.warnings or []),
                status=row.status,
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

    @property
    def etf_profile_fields(self) -> Any:
        uow = self

        class _EtfProfileFieldsView:
            @staticmethod
            def add(evidence: FieldEvidence) -> FieldEvidence:
                return uow._etf_profile_fields_add(evidence)

            @staticmethod
            def upsert(evidence: FieldEvidence) -> FieldEvidence:
                return uow._etf_profile_fields_add(evidence)

            @staticmethod
            def get_by_instrument(instrument_id: UUID) -> list[FieldEvidence]:
                return uow._etf_profile_fields_get_by_instrument(instrument_id)

        return _EtfProfileFieldsView()

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
    field_evidence_add_calls: list[FieldEvidence] | None = None,
    batches_by_attempt: dict[UUID, list[StoredProviderBatch]] | None = None,
    field_evidence_rows: list[FieldEvidence] | None = None,
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
            field_evidence_add_calls=field_evidence_add_calls,
            batches_by_attempt=batches_by_attempt,
            field_evidence_rows=field_evidence_rows,
        )

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _attempt_payload(session: MagicMock) -> str:
    attempt_rows = [row for row in session.added_rows if isinstance(row, ProviderAttemptRow)]
    assert len(attempt_rows) == 1, f"exactly one attempt row, got {len(attempt_rows)}"
    payload = attempt_rows[0].response_payload_json
    assert payload is not None, "attempt must carry the sidecar"
    return str(payload)


def _request_payload(session: MagicMock) -> tuple[str, str]:
    request_rows = [row for row in session.added_rows if isinstance(row, ProviderRequestRow)]
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
            row for row in self._session.added_rows if isinstance(row, ProviderRequestRow)
        ]
        attempt_rows = [
            row for row in self._session.added_rows if isinstance(row, ProviderAttemptRow)
        ]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(attempt_rows[0].status, "failed")
        self.assertEqual(attempt_rows[0].error_code, "ProviderBadResponseError")
        # No raw.provider_batches row is created for a failed attempt.
        from invest_storage.models import RawProviderBatchRow

        batch_rows = [
            row for row in self._session.added_rows if isinstance(row, RawProviderBatchRow)
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
        field_evidence_add_calls: list[FieldEvidence] | None = None,
        batches_by_attempt: dict[UUID, list[StoredProviderBatch]] | None = None,
    ) -> tuple[Any, Any]:
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=self._instrument_lookup,
            profile_upsert_calls=upsert_calls,
            field_evidence_add_calls=field_evidence_add_calls,
            batches_by_attempt=batches_by_attempt,
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

        self.assertEqual(summary, UpsertSummary(inserted=2, skipped=0, evidence_rows=6))
        self.assertEqual(len(upsert_calls), 2)
        # First record: SSE 510300
        first = upsert_calls[0]
        self.assertEqual(first.instrument_id, self._instrument_id_510300)
        self.assertEqual(first.fund_type, "ETF")
        self.assertEqual(first.category, "ETF")
        self.assertEqual(first.shares, __import__("decimal").Decimal("1000000000"))
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

        self.assertEqual(summary, UpsertSummary(inserted=1, skipped=1, evidence_rows=3))
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

        self.assertEqual(summary, UpsertSummary(inserted=1, skipped=3, evidence_rows=3))
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

        self.assertEqual(first_summary, UpsertSummary(inserted=1, skipped=0, evidence_rows=3))
        self.assertEqual(second_summary, UpsertSummary(inserted=1, skipped=0, evidence_rows=3))
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

        self.assertEqual(summary, UpsertSummary(inserted=0, skipped=0, evidence_rows=0))
        self.assertEqual(upsert_calls, [])

    def _make_upsert_session(
        self,
        *,
        attempts: list[StoredProviderAttempt],
        upsert_calls: list[EtfProfile],
    ) -> tuple[Any, Any]:
        return self._build_upsert_session(attempts=attempts, upsert_calls=upsert_calls)

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


class UpsertEtfProfileFieldEvidenceTest(unittest.TestCase):
    """``upsert_etf_profiles`` must persist :class:`FieldEvidence` rows
    through ``uow.etf_profile_fields`` for every successful AkShare
    profile snapshot.

    The slice wires the existing PR-ETF-PROFILE-02 mapper
    (:func:`invest_pipeline.adapters.akshare.mapper.map_etf_profile_to_field_evidence`)
    into the application service so each successful AkShare
    ``akshare/fund_name_em + fund_etf_spot_em`` snapshot lands three
    :class:`FieldEvidence` rows per profile record
    (``FUND_TYPE`` / ``CATEGORY`` / ``SHARES``) into
    ``analytics.etf_profile_fields``. The repository's
    ``ON CONFLICT (content_hash) DO NOTHING`` contract keeps the
    audit table stable across re-runs; the slice therefore invokes
    ``uow.etf_profile_fields.add`` on every upsert and the storage
    layer is the single source of truth for the
    ``content_hash``-keyed idempotency.

    The tests pin:

    - the closed-set ``FUND_TYPE`` / ``CATEGORY`` / ``SHARES``
      vocabulary (no ``AUM`` / ``MARKET_VALUE`` leak);
    - the source provenance propagation (provider_key /
      dataset_key / observed_at / source_batch_id / revision /
      confidence_score);
    - the duplicate / idempotency contract at the application layer
      (the storage layer's ``ON CONFLICT DO NOTHING`` is exercised
      through the ``content_hash`` identity, not the slice);
    - the records-without-an-instrument skip path (no evidence row
      is written for an unknown ``core.instruments`` id);
    - the ``source_batch_id`` resolution from
      ``raw.provider_batches`` (and the ``None`` fallback when no
      batch was persisted, e.g. a ``partial`` attempt).
    """

    def setUp(self) -> None:
        self._provider_key = "akshare"
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key=self._provider_key,
            dataset_key="etf_profile",
            request_key="etf-profile",
            request_params={},
            status="succeeded",
        )
        self._instrument_id_510300 = uuid4()
        self._instrument_id_159919 = uuid4()
        self._finished_at = datetime(2026, 7, 30, 8, 0, 5, tzinfo=UTC)
        self._started_at = datetime(2026, 7, 30, 8, 0, 0, tzinfo=UTC)

    def _instrument_lookup(self, *, exchange: str, symbol: str) -> _StubInstrument | None:
        if symbol == "510300" and exchange == "SSE":
            return _StubInstrument(instrument_id=self._instrument_id_510300)
        if symbol == "159919" and exchange == "SZSE":
            return _StubInstrument(instrument_id=self._instrument_id_159919)
        return None

    def _build_sidecar(self, records: list[dict[str, Any]]) -> str:
        return json.dumps(
            {"schema_version": 1, "records": records},
            ensure_ascii=False,
            sort_keys=True,
        )

    def _stored_attempt(
        self,
        *,
        attempt_id: UUID,
        attempt_no: int = 1,
        sidecar_json: str | None,
        finished_at: datetime,
    ) -> StoredProviderAttempt:
        return StoredProviderAttempt(
            id=attempt_id,
            provider_request_id=self._provider_request_id,
            attempt_no=attempt_no,
            started_at=self._started_at,
            finished_at=finished_at,
            status="succeeded",
            error_stage=None,
            error_code=None,
            error_message=None,
            response_payload_sha256="0" * 64,
            response_payload_json=sidecar_json,
        )

    def _stored_batch(
        self, *, attempt_id: UUID, batch_id: UUID | None = None
    ) -> StoredProviderBatch:
        return StoredProviderBatch(
            id=batch_id or uuid4(),
            provider_request_id=self._provider_request_id,
            provider_attempt_id=attempt_id,
            provider_key=self._provider_key,
            dataset_key="etf_profile",
            record_count=1,
            payload_sha256="0" * 64,
            warnings=[],
            status="succeeded",
        )

    def _run_upsert(
        self,
        *,
        attempt_id: UUID,
        sidecar: str,
        batch: StoredProviderBatch | None,
        field_evidence_rows: list[FieldEvidence] | None = None,
    ) -> tuple[UpsertSummary, list[FieldEvidence], list[EtfProfile]]:
        attempts = [
            self._stored_attempt(
                attempt_id=attempt_id,
                sidecar_json=sidecar,
                finished_at=self._finished_at,
            ),
        ]
        batches_by_attempt: dict[UUID, list[StoredProviderBatch]] = {}
        if batch is not None:
            batches_by_attempt[attempt_id] = [batch]
        profile_calls: list[EtfProfile] = []
        evidence_calls: list[FieldEvidence] = []
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=self._instrument_lookup,
            profile_upsert_calls=profile_calls,
            field_evidence_add_calls=evidence_calls,
            batches_by_attempt=batches_by_attempt,
            field_evidence_rows=field_evidence_rows,
        )
        summary = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )
        return summary, evidence_calls, profile_calls

    def test_canonical_profile_is_projected_from_resolved_evidence(self) -> None:
        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": "ETF",
                    "category": "Equity",
                    "shares": "1000000000",
                }
            ]
        )
        summary, _evidence, profiles = self._run_upsert(
            attempt_id=uuid4(),
            sidecar=sidecar,
            batch=self._stored_batch(attempt_id=uuid4()),
        )
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].fund_type, "ETF")
        self.assertEqual(profiles[0].category, "Equity")
        self.assertEqual(profiles[0].shares, Decimal("1000000000"))

    def test_conflicting_evidence_does_not_overwrite_canonical_field(self) -> None:
        instrument_id = InstrumentId(self._instrument_id_510300)
        prior = map_etf_profile_to_field_evidence(
            AkshareProfileMappingResult(
                records=(
                    AkshareProfileRecord(
                        symbol="510300",
                        exchange="SSE",
                        fund_type="ETF",
                        category="Bond",
                        shares=Decimal("1000000000"),
                    ),
                ),
                warnings=(),
            ),
            instrument_id_resolver=lambda _symbol, _exchange: instrument_id,
            source_batch_id=uuid4(),
            observed_at=datetime(2026, 8, 4, tzinfo=UTC),
            confidence_score=Decimal("0.8"),
            revision=1,
        ).evidence
        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": "ETF",
                    "category": "Equity",
                    "shares": "1000000000",
                }
            ]
        )
        _summary, _evidence, profiles = self._run_upsert(
            attempt_id=uuid4(),
            sidecar=sidecar,
            batch=self._stored_batch(attempt_id=uuid4()),
            field_evidence_rows=list(prior),
        )
        self.assertEqual(len(profiles), 1)
        self.assertIsNone(profiles[0].category)
        self.assertEqual(profiles[0].fund_type, "ETF")

    def test_field_evidence_rows_match_three_per_profile_record(self) -> None:
        # The AkShare ETF Profile mapper emits exactly three evidence
        # rows per ``AkshareProfileRecord``: ``FUND_TYPE`` (TEXT),
        # ``CATEGORY`` (TEXT), ``SHARES`` (DECIMAL). A two-record
        # snapshot therefore persists six evidence rows.
        sidecar = self._build_sidecar(
            [
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
            ]
        )
        attempt_id = uuid4()
        batch = self._stored_batch(attempt_id=attempt_id)
        summary, evidence_calls, _ = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=batch
        )
        self.assertEqual(summary.evidence_rows, 6)
        self.assertEqual(len(evidence_calls), 6)
        # Verify the closed-set vocabulary: exactly FUND_TYPE /
        # CATEGORY / SHARES, in that order, per record.
        from invest_domain.etf_profile.models import FieldKey, FieldValueType

        expected_keys_per_record = [
            FieldKey.FUND_TYPE,
            FieldKey.CATEGORY,
            FieldKey.SHARES,
        ]
        self.assertEqual(
            [entry.field_key for entry in evidence_calls],
            expected_keys_per_record + expected_keys_per_record,
        )
        self.assertEqual(
            [entry.value_type for entry in evidence_calls],
            [
                FieldValueType.TEXT,
                FieldValueType.TEXT,
                FieldValueType.DECIMAL,
                FieldValueType.TEXT,
                FieldValueType.TEXT,
                FieldValueType.DECIMAL,
            ],
        )
        # No AUM / MARKET_VALUE / TURNOVER_VALUE rows.
        emitted_keys = {entry.field_key for entry in evidence_calls}
        self.assertNotIn(FieldKey.AUM, emitted_keys)
        self.assertNotIn(FieldKey.MARKET_VALUE, emitted_keys)
        self.assertNotIn(FieldKey.TURNOVER_VALUE, emitted_keys)

    def test_field_evidence_rows_carry_source_provenance(self) -> None:
        # The upstream batch id, attempt finished_at, provider / dataset
        # keys and confidence score must propagate to every
        # :class:`FieldEvidence` row so the audit chain can trace a
        # piece of evidence back to its origin.
        attempt_id = uuid4()
        batch_id = uuid4()
        batch = self._stored_batch(attempt_id=attempt_id, batch_id=batch_id)
        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": "ETF",
                    "category": "ETF",
                    "shares": "1000000000",
                },
            ]
        )
        _summary, evidence_calls, _ = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=batch
        )
        self.assertEqual(len(evidence_calls), 3)
        for evidence in evidence_calls:
            self.assertEqual(evidence.source.provider_key, "akshare")
            self.assertEqual(evidence.source.dataset_key, "etf_profile")
            self.assertEqual(evidence.source.observed_at, self._finished_at)
            self.assertEqual(evidence.source.source_batch_id, batch_id)
            self.assertEqual(evidence.source.revision, 1)
            self.assertEqual(evidence.confidence_score, Decimal("0.9"))

    def test_field_evidence_source_batch_id_is_none_when_no_batch(self) -> None:
        # A successful attempt with no batch (e.g. the
        # ``ProviderAttemptStatus.SUCCEEDED`` + ``batch is None`` arm
        # of ``write_etf_profiles_raw``) produces a ``partial``
        # request with no ``raw.provider_batches`` row. The slice
        # must still persist evidence rows, just with
        # ``source_batch_id=None`` so the audit chain stays anchored
        # to the attempt rather than to a non-existent batch.
        attempt_id = uuid4()
        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": "ETF",
                    "category": "ETF",
                    "shares": "1000000000",
                },
            ]
        )
        _summary, evidence_calls, _ = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=None
        )
        self.assertEqual(len(evidence_calls), 3)
        for evidence in evidence_calls:
            self.assertIsNone(evidence.source.source_batch_id)
            # Other provenance still propagates.
            self.assertEqual(evidence.source.provider_key, "akshare")
            self.assertEqual(evidence.source.dataset_key, "etf_profile")
            self.assertEqual(evidence.source.observed_at, self._finished_at)

    def test_field_evidence_skips_records_with_unknown_instrument(self) -> None:
        # A sidecar record whose ``(symbol, exchange)`` does not
        # resolve to a known ``core.instruments`` row must NOT
        # produce a field-evidence row: the evidence table's FK
        # points at ``core.instruments.id`` so a phantom evidence
        # row would crash the storage layer. The core profile
        # upsert already short-circuits in this case; the
        # field-evidence pass inherits the same skip.
        sidecar = self._build_sidecar(
            [
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
            ]
        )
        attempt_id = uuid4()
        batch = self._stored_batch(attempt_id=attempt_id)
        summary, evidence_calls, profile_calls = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=batch
        )
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.evidence_rows, 3)
        self.assertEqual(len(profile_calls), 1)
        self.assertEqual(len(evidence_calls), 3)
        # The surviving evidence rows all reference the resolved
        # 510300 instrument id; no evidence row references the
        # unknown 999999 placeholder.
        for evidence in evidence_calls:
            self.assertEqual(evidence.instrument_id, self._instrument_id_510300)

    def test_field_evidence_is_idempotent_on_duplicate_run(self) -> None:
        # The repository's ``ON CONFLICT (content_hash) DO NOTHING``
        # contract is exercised at the storage layer, but the slice
        # itself is required to call ``uow.etf_profile_fields.add``
        # for every observed evidence row. A re-run with identical
        # business content produces an additional ``add`` invocation
        # for every row; the storage layer's idempotency guard
        # ensures the audit table stays at the same row count.
        # Pin the application-level contract here.
        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": "ETF",
                    "category": "ETF",
                    "shares": "1000000000",
                },
            ]
        )
        attempts = [
            self._stored_attempt(
                attempt_id=uuid4(),
                sidecar_json=sidecar,
                finished_at=self._finished_at,
            ),
        ]
        batches_by_attempt: dict[UUID, list[StoredProviderBatch]] = {
            attempts[0].id: [self._stored_batch(attempt_id=attempts[0].id)]
        }
        evidence_calls: list[FieldEvidence] = []
        session = _build_session()
        uow_factory = _make_uow_factory(
            session,
            stored_request=self._stored_request,
            attempts=attempts,
            instrument_lookup=self._instrument_lookup,
            profile_upsert_calls=[],
            field_evidence_add_calls=evidence_calls,
            batches_by_attempt=batches_by_attempt,
        )
        first = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )
        second = upsert_etf_profiles(
            _make_session_factory(session),
            unit_of_work_factory=uow_factory,
        )
        self.assertEqual(first.evidence_rows, 3)
        self.assertEqual(second.evidence_rows, 3)
        # Six add invocations total (3 per run); the storage layer's
        # idempotency guard is what makes the second batch a no-op at
        # the audit table — not a slice-level skip.
        self.assertEqual(len(evidence_calls), 6)
        # The two runs produce identical content_hashes (the
        # business content is the same); the storage layer would
        # therefore collapse the duplicates to a single audit row.
        first_hashes = sorted(entry.content_hash for entry in evidence_calls[:3])
        second_hashes = sorted(entry.content_hash for entry in evidence_calls[3:])
        self.assertEqual(first_hashes, second_hashes)

    def test_field_evidence_does_not_run_on_empty_sidecar(self) -> None:
        # A quiet AkShare response yields an empty sidecar so the
        # service returns ``UpsertSummary(0, 0, 0)``; the evidence
        # pass is short-circuited and no add invocation happens.
        sidecar = self._build_sidecar([])
        attempt_id = uuid4()
        summary, evidence_calls, profile_calls = self._run_upsert(
            attempt_id=attempt_id,
            sidecar=sidecar,
            batch=self._stored_batch(attempt_id=attempt_id),
        )
        self.assertEqual(summary, UpsertSummary(0, 0, 0))
        self.assertEqual(evidence_calls, [])
        self.assertEqual(profile_calls, [])

    def test_field_evidence_resolves_instrument_ids_from_sidecar(
        self,
    ) -> None:
        # The mapper's ``instrument_id_resolver`` is fed
        # ``(symbol, exchange)`` from the sidecar; the resulting
        # evidence rows must carry the resolved
        # ``core.instruments.id`` (not the provider-native symbol
        # nor a placeholder). Pin the propagation so a future
        # refactor that drops the resolver shortcut surfaces
        # immediately.
        sidecar = self._build_sidecar(
            [
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
            ]
        )
        attempt_id = uuid4()
        batch = self._stored_batch(attempt_id=attempt_id)
        _summary, evidence_calls, _ = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=batch
        )
        self.assertEqual(len(evidence_calls), 6)
        by_record: dict[UUID, int] = {}
        for evidence in evidence_calls:
            by_record[evidence.instrument_id] = by_record.get(evidence.instrument_id, 0) + 1
        self.assertEqual(
            by_record,
            {
                self._instrument_id_510300: 3,
                self._instrument_id_159919: 3,
            },
        )

    def test_field_evidence_quality_status_reflects_optional_fields(
        self,
    ) -> None:
        # When a sidecar record omits ``fund_type`` / ``category`` /
        # ``shares`` the mapper must emit the matching
        # :class:`FieldEvidence` row with
        # :attr:`QualityStatus.MISSING` and a ``None`` value so the
        # downstream resolver can distinguish ``unknown`` from a
        # real zero / empty value.
        from invest_domain.research.models import QualityStatus

        sidecar = self._build_sidecar(
            [
                {
                    "symbol": "510300",
                    "exchange": "SSE",
                    "fund_type": None,
                    "category": "Equity",
                    "shares": None,
                },
            ]
        )
        attempt_id = uuid4()
        batch = self._stored_batch(attempt_id=attempt_id)
        _summary, evidence_calls, _ = self._run_upsert(
            attempt_id=attempt_id, sidecar=sidecar, batch=batch
        )
        self.assertEqual(len(evidence_calls), 3)
        from invest_domain.etf_profile.models import FieldKey

        self.assertEqual(evidence_calls[0].field_key, FieldKey.FUND_TYPE)
        self.assertIsNone(evidence_calls[0].value)
        self.assertEqual(evidence_calls[0].quality_status, QualityStatus.MISSING)
        self.assertEqual(evidence_calls[1].field_key, FieldKey.CATEGORY)
        self.assertEqual(evidence_calls[1].value, "Equity")
        self.assertEqual(evidence_calls[1].quality_status, QualityStatus.COMPLETE)
        self.assertEqual(evidence_calls[2].field_key, FieldKey.SHARES)
        self.assertIsNone(evidence_calls[2].value)
        self.assertEqual(evidence_calls[2].quality_status, QualityStatus.MISSING)

    def test_field_evidence_does_not_write_when_request_missing(
        self,
    ) -> None:
        # No ``raw.provider_requests`` row → ``LookupError`` is
        # raised before the evidence pass starts; the audit table
        # is untouched.
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


if __name__ == "__main__":
    unittest.main()
