"""Repository implementations for the M1 Storage layer.

Each repository owns its ORM-to-domain mapping: callers always receive
domain objects, never SQLAlchemy ORM rows.

PR-02 introduced the three-layer evidence model in
``raw.provider_requests`` / ``raw.provider_attempts`` /
``raw.provider_batches`` (see ADR-0003 §6). The repositories in this
module cover:

- :class:`SqlAlchemyInstrumentRepository` — canonical
  ``core.instruments`` rows. The partial unique index on
  ``(symbol, exchange) WHERE delist_date IS NULL`` is the natural
  business-key upsert target.
- :class:`SqlAlchemyProviderRequestRepository` — one row per logical
  request, identified by ``(provider_key, dataset_key, request_key)``.
  :meth:`get_or_create` is the idempotent entry point used by the
  application service.
- :class:`SqlAlchemyProviderAttemptRepository` — one row per
  network/SDK attempt; carries lifecycle status and error metadata.
  :meth:`start` opens an attempt, :meth:`mark_succeeded` /
  :meth:`mark_failed` close it.
- :class:`SqlAlchemyProviderBatchRepository` — one row per
  successful/partial batch. Inserted only when the parent attempt
  succeeded or partially succeeded.
- :class:`SqlAlchemyPipelineRunRepository` — one row per execution of
  a pipeline job in ``ops.pipeline_runs``.
- :class:`SqlAlchemyCandidatePoolRunRepository` — one row per
  candidate-pool calculation in ``analytics.candidate_pool_runs``.
  Drives the legal state-machine transitions through
  :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`.
- :class:`SqlAlchemyCandidatePoolItemRepository` — per-instrument
  judgments belonging to a run, persisted in
  ``analytics.candidate_pool_items``.

Each domain-side dataclass is free of SQLAlchemy machinery, so
application / domain code can pass them around without importing the
storage layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
    ExclusionReason,
    RuleOutcome,
    RuleSeverity,
)
from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_domain.shared.canonical import CANONICAL_HASH_SCHEMA_VERSION
from invest_domain.shared.values import Currency
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invest_storage.models import (
    CandidatePoolItemRow,
    CandidatePoolRunRow,
    DailyBarRow,
    InputSnapshotRow,
    InstrumentRow,
    PipelineRunRow,
    ProviderAttemptRow,
    ProviderRequestRow,
    RawProviderBatchRow,
)


@dataclass(frozen=True, slots=True)
class StoredProviderRequest:
    """Domain-side view of a persisted ``raw.provider_requests`` row."""

    id: UUID
    provider_key: str
    dataset_key: str
    request_key: str
    request_params: dict[str, Any] = field(default_factory=dict)
    requested_by_run_id: UUID | None = None
    status: str = "pending"
    created_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderRequest:
    """Input shape for :meth:`SqlAlchemyProviderRequestRepository.add`."""

    provider_key: str
    dataset_key: str
    request_key: str
    status: str = "pending"
    request_params: dict[str, Any] = field(default_factory=dict)
    requested_by_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredProviderAttempt:
    """Domain-side view of a persisted ``raw.provider_attempts`` row."""

    id: UUID
    provider_request_id: UUID
    attempt_no: int
    provider_request_id_text: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = "running"
    http_status: int | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_payload_sha256: str | None = None
    response_payload_json: Any | None = None
    response_payload_uri: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderAttempt:
    """Input shape for :meth:`SqlAlchemyProviderAttemptRepository.add`."""

    provider_request_id: UUID
    attempt_no: int
    started_at: datetime
    status: str = "running"
    provider_request_id_text: str | None = None
    finished_at: datetime | None = None
    http_status: int | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_payload_sha256: str | None = None
    response_payload_json: Any | None = None
    response_payload_uri: str | None = None


@dataclass(frozen=True, slots=True)
class StoredProviderBatch:
    """Domain-side view of a persisted ``raw.provider_batches`` row."""

    id: UUID
    provider_request_id: UUID
    provider_attempt_id: UUID
    provider_key: str
    dataset_key: str
    record_count: int
    payload_sha256: str
    warnings: list[Any] = field(default_factory=list)
    status: str = "succeeded"
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProviderBatch:
    """Input shape for :meth:`SqlAlchemyProviderBatchRepository.add`.

    ``provider_request_id`` and ``provider_attempt_id`` are mandatory FKs
    pointing to the parent request and attempt rows; the application
    service persists them in order (request → attempt → batch) and
    threads the assigned UUIDs through.
    """

    provider_request_id: UUID
    provider_attempt_id: UUID
    provider_key: str
    dataset_key: str
    record_count: int
    payload_sha256: str
    status: str = "succeeded"
    warnings: list[Any] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StoredDailyBar:
    """Domain-side view of a persisted ``core.daily_bars`` row.

    Carries every field the :class:`invest_domain.market_data.models.DailyBar`
    needs to be reconstructed, plus the storage-assigned ``id`` and
    server-generated ``created_at``. ``row_hash`` is the deterministic
    business-content digest the domain validated at construction time;
    callers that want a full :class:`DailyBar` instance should rebuild it
    through :meth:`DailyBar.build` so the domain invariants run again
    on the round-trip.
    """

    id: UUID
    instrument_id: UUID
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: str
    trading_status: str
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    revision: int
    row_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewDailyBar:
    """Input shape for :meth:`SqlAlchemyDailyBarRepository.upsert_many`.

    The caller is responsible for validating the OHLCV business content
    through :class:`invest_domain.market_data.models.DailyBar` before
    handing the bar to the repository; this dataclass is the
    "transport" shape the application service uses. ``revision`` on
    the input is taken as ``1`` and the repository may bump it to
    ``latest + 1`` when the business content has actually changed (see
    ADR-0006 §3).
    """

    instrument_id: UUID
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    adjustment: Adjust
    trading_status: TradingStatus
    source_provider: str
    source_batch_id: UUID | None
    observed_at: datetime
    row_hash: str


class SqlAlchemyInstrumentRepository:
    """CRUD + UUID upsert for the canonical ``core.instruments`` table.

    The repository is stateless apart from its session: callers obtain a
    fresh repository per UnitOfWork so the session lifetime is owned by
    the UoW (or by the caller of :func:`invest_storage.database.session_scope`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, instruments: Sequence[Instrument]) -> int:
        """Insert or update a batch of instruments; returns the count.

        Instruments carrying an explicit ``instrument_id`` are upserted by
        primary key (so an explicit re-import can rewrite the row). The
        remainder are upserted by the partial unique business key
        ``(symbol, exchange) WHERE delist_date IS NULL`` - re-imports of
        an existing active instrument keep the original ``id``.
        """

        if not instruments:
            return 0

        with_id: list[Instrument] = []
        without_id: list[Instrument] = []
        for item in instruments:
            if item.instrument_id is None:
                without_id.append(item)
            else:
                with_id.append(item)

        total = 0
        if with_id:
            total += self._upsert_by_id(with_id)
        if without_id:
            total += self._upsert_by_business_key(without_id)
        return total

    def get_by_id(self, instrument_id: UUID | InstrumentId) -> Instrument | None:
        raw_id = instrument_id.value if isinstance(instrument_id, InstrumentId) else instrument_id
        row = self._session.get(InstrumentRow, raw_id)
        return _row_to_instrument(row) if row is not None else None

    def get_by_business_key(
        self, *, exchange: str, symbol: str
    ) -> Instrument | None:
        """Return the active instrument carrying the given business key.

        Uses the partial unique index on ``(symbol, exchange) WHERE
        delist_date IS NULL``; delisted rows are ignored. Returns
        ``None`` when no active row matches.
        """

        stmt = (
            select(InstrumentRow)
            .where(
                InstrumentRow.symbol == symbol,
                InstrumentRow.exchange == exchange,
                InstrumentRow.delist_date.is_(None),
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_instrument(row) if row is not None else None

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]:
        rows = self._session.scalars(
            select(InstrumentRow)
            .where(InstrumentRow.is_active.is_(True))
            .order_by(InstrumentRow.exchange, InstrumentRow.symbol)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_instrument(row) for row in rows]

    def count_active(self) -> int:
        stmt = select(InstrumentRow.id).where(InstrumentRow.is_active.is_(True))
        return len(self._session.scalars(stmt).all())

    def _upsert_by_id(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": item.instrument_id.value,  # type: ignore[union-attr]
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.id],
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)

    def _upsert_by_business_key(self, instruments: Sequence[Instrument]) -> int:
        values = [
            {
                "id": uuid.uuid4(),
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
                "instrument_type": item.instrument_type.value,
                "currency": _currency_value(item.currency),
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "status": _status_value(item.status),
                "underlying_index": item.underlying_index,
                "category": item.category,
                "provider_symbol_map": _provider_symbol_map(item.provider_symbol_map),
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "is_active": item.is_active,
            }
            for item in instruments
        ]
        statement = insert(InstrumentRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentRow.symbol, InstrumentRow.exchange],
            index_where=InstrumentRow.delist_date.is_(None),
            set_=_excluded_set(),
        )
        self._session.execute(statement)
        return len(values)


class SqlAlchemyProviderRequestRepository:
    """Read/write access to ``raw.provider_requests``.

    A ``raw.provider_requests`` row is identified by the natural unique
    key ``(provider_key, dataset_key, request_key)``; the database
    enforces uniqueness. :meth:`get_or_create` is the idempotent entry
    point used by the application service when a logical request is
    re-issued: an existing row is returned untouched instead of raising
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, request: NewProviderRequest) -> StoredProviderRequest:
        row = ProviderRequestRow(
            id=uuid.uuid4(),
            provider_key=request.provider_key,
            dataset_key=request.dataset_key,
            request_key=request.request_key,
            request_params=dict(request.request_params),
            requested_by_run_id=request.requested_by_run_id,
            status=request.status,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_request(row)

    def get_by_id(self, request_id: UUID) -> StoredProviderRequest | None:
        row = self._session.get(ProviderRequestRow, request_id)
        return _row_to_stored_request(row) if row is not None else None

    def get_by_logical_key(
        self, *, provider_key: str, dataset_key: str, request_key: str
    ) -> StoredProviderRequest | None:
        stmt = (
            select(ProviderRequestRow)
            .where(
                ProviderRequestRow.provider_key == provider_key,
                ProviderRequestRow.dataset_key == dataset_key,
                ProviderRequestRow.request_key == request_key,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_stored_request(row) if row is not None else None

    def get_or_create(self, request: NewProviderRequest) -> StoredProviderRequest:
        existing = self.get_by_logical_key(
            provider_key=request.provider_key,
            dataset_key=request.dataset_key,
            request_key=request.request_key,
        )
        if existing is not None:
            return existing
        try:
            return self.add(request)
        except Exception:
            self._session.rollback()
            existing = self.get_by_logical_key(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
            )
            if existing is not None:
                return existing
            raise

    def mark_status(
        self,
        request_id: UUID,
        *,
        status: str,
        completed_at: datetime | None = None,
    ) -> StoredProviderRequest:
        row = self._session.get(ProviderRequestRow, request_id)
        if row is None:
            raise LookupError(
                f"ProviderRequest {request_id!s} not found; cannot update status"
            )
        row.status = status
        if completed_at is not None:
            row.completed_at = completed_at
        self._session.flush()
        return _row_to_stored_request(row)


class SqlAlchemyProviderAttemptRepository:
    """Read/write access to ``raw.provider_attempts``.

    The repository owns the lifecycle transitions for an attempt:
    :meth:`start` opens a new attempt in the ``running`` state,
    :meth:`mark_succeeded` / :meth:`mark_failed` close it. The database
    CHECK constraint ``ck_provider_attempts_succeeded_has_hash`` and
    ``ck_provider_attempts_failed_has_error`` enforce the contract that
    a successful attempt MUST carry a response SHA-256 and a failed
    attempt MUST carry ``error_stage`` and ``error_code``; the
    repository surfaces those violations via :class:`ValueError` /
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: NewProviderAttempt) -> StoredProviderAttempt:
        row = ProviderAttemptRow(
            id=uuid.uuid4(),
            provider_request_id=attempt.provider_request_id,
            attempt_no=attempt.attempt_no,
            provider_request_id_text=attempt.provider_request_id_text,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            status=attempt.status,
            http_status=attempt.http_status,
            error_stage=attempt.error_stage,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            response_payload_sha256=attempt.response_payload_sha256,
            response_payload_json=attempt.response_payload_json,
            response_payload_uri=attempt.response_payload_uri,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_attempt(row)

    def start(
        self,
        *,
        provider_request_id: UUID,
        attempt_no: int,
        started_at: datetime,
        provider_request_id_text: str | None = None,
    ) -> StoredProviderAttempt:
        """Open a new ``running`` attempt for the given request.

        Raises :class:`ValueError` if ``attempt_no < 1``; the database
        ``UNIQUE(provider_request_id, attempt_no)`` constraint will
        reject duplicate ``attempt_no`` values via
        :class:`sqlalchemy.exc.IntegrityError`.
        """

        if attempt_no < 1:
            raise ValueError(f"attempt_no must be >= 1, got {attempt_no}")
        return self.add(
            NewProviderAttempt(
                provider_request_id=provider_request_id,
                attempt_no=attempt_no,
                started_at=started_at,
                status="running",
                provider_request_id_text=provider_request_id_text,
            )
        )

    def mark_succeeded(
        self,
        attempt_id: UUID,
        *,
        finished_at: datetime,
        response_payload_sha256: str,
        response_payload_json: Any | None = None,
        response_payload_uri: str | None = None,
        http_status: int | None = None,
    ) -> StoredProviderAttempt:
        """Transition an attempt into the ``succeeded`` terminal state.

        ``response_payload_sha256`` is required by the database CHECK
        constraint. The repository raises :class:`ValueError` when the
        hash is empty so a meaningless record is never persisted.
        """

        if not response_payload_sha256 or not response_payload_sha256.strip():
            raise ValueError(
                "mark_succeeded requires a non-empty response_payload_sha256"
            )
        row = self._session.get(ProviderAttemptRow, attempt_id)
        if row is None:
            raise LookupError(
                f"ProviderAttempt {attempt_id!s} not found; cannot mark succeeded"
            )
        row.status = "succeeded"
        row.finished_at = finished_at
        row.response_payload_sha256 = response_payload_sha256
        row.response_payload_json = response_payload_json
        row.response_payload_uri = response_payload_uri
        if http_status is not None:
            row.http_status = http_status
        self._session.flush()
        return _row_to_stored_attempt(row)

    def mark_failed(
        self,
        attempt_id: UUID,
        *,
        finished_at: datetime,
        error_stage: str,
        error_code: str,
        error_message: str | None = None,
        http_status: int | None = None,
    ) -> StoredProviderAttempt:
        """Transition an attempt into the ``failed`` terminal state.

        ``error_stage`` and ``error_code`` are required by the database
        CHECK constraint. The repository raises :class:`ValueError`
        when either is empty so a meaningless record is never persisted.
        """

        if not error_stage or not error_stage.strip():
            raise ValueError("mark_failed requires a non-empty error_stage")
        if not error_code or not error_code.strip():
            raise ValueError("mark_failed requires a non-empty error_code")
        row = self._session.get(ProviderAttemptRow, attempt_id)
        if row is None:
            raise LookupError(
                f"ProviderAttempt {attempt_id!s} not found; cannot mark failed"
            )
        row.status = "failed"
        row.finished_at = finished_at
        row.error_stage = error_stage
        row.error_code = error_code
        row.error_message = error_message
        if http_status is not None:
            row.http_status = http_status
        self._session.flush()
        return _row_to_stored_attempt(row)

    def get_by_id(self, attempt_id: UUID) -> StoredProviderAttempt | None:
        row = self._session.get(ProviderAttemptRow, attempt_id)
        return _row_to_stored_attempt(row) if row is not None else None

    def list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[StoredProviderAttempt]:
        rows = self._session.scalars(
            select(ProviderAttemptRow)
            .where(ProviderAttemptRow.provider_request_id == request_id)
            .order_by(ProviderAttemptRow.attempt_no.asc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_attempt(row) for row in rows]


class SqlAlchemyProviderBatchRepository:
    """Read/write access to ``raw.provider_batches``.

    Only successful/partial attempts produce a batch row. The repository
    does not enforce the ``status`` value set itself - the database
    CHECK constraint ``ck_provider_batches_status_valid`` rejects
    ``FAILED`` and any other out-of-vocabulary value. The FK constraints
    on ``provider_request_id`` and ``provider_attempt_id`` reject
    batches with missing parents via
    :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, batch: NewProviderBatch) -> StoredProviderBatch:
        row = RawProviderBatchRow(
            id=uuid.uuid4(),
            provider_request_id=batch.provider_request_id,
            provider_attempt_id=batch.provider_attempt_id,
            provider_key=batch.provider_key,
            dataset_key=batch.dataset_key,
            record_count=batch.record_count,
            payload_sha256=batch.payload_sha256,
            warnings=list(batch.warnings),
            status=batch.status,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_stored_batch(row)

    def get_by_id(self, batch_id: UUID) -> StoredProviderBatch | None:
        row = self._session.get(RawProviderBatchRow, batch_id)
        return _row_to_stored_batch(row) if row is not None else None

    def list_by_attempt(
        self, attempt_id: UUID, *, limit: int = 10, offset: int = 0
    ) -> Sequence[StoredProviderBatch]:
        rows = self._session.scalars(
            select(RawProviderBatchRow)
            .where(RawProviderBatchRow.provider_attempt_id == attempt_id)
            .order_by(RawProviderBatchRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_batch(row) for row in rows]

    def list_by_provider_dataset(
        self, *, provider_key: str, dataset_key: str, limit: int = 100, offset: int = 0
    ) -> Sequence[StoredProviderBatch]:
        rows = self._session.scalars(
            select(RawProviderBatchRow)
            .where(
                RawProviderBatchRow.provider_key == provider_key,
                RawProviderBatchRow.dataset_key == dataset_key,
            )
            .order_by(RawProviderBatchRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_row_to_stored_batch(row) for row in rows]


class SqlAlchemyDailyBarRepository:
    """Read/write access to ``core.daily_bars`` with ADR-0006 revision semantics.

    The repository owns the revision-allocation algorithm defined in
    ADR-0006 §3: a write only advances the revision when the incoming
    business content (as identified by ``row_hash``) differs from the
    latest persisted row for ``(instrument_id, trade_date, adjustment)``.
    Re-collects of the same business content are a no-op; the new
    ``raw.provider_batches`` row still records the audit trail but no
    additional ``core.daily_bars`` row is created.

    All write paths route through :meth:`upsert_many`; there is no
    single-row ``add`` so callers cannot accidentally bypass the
    row-hash comparison. The database-level ``UNIQUE (instrument_id,
    trade_date, adjustment, revision)`` constraint is the final
    concurrency guard, but the repository reads the latest revision
    inside the same UnitOfWork so the deterministic content comparison
    runs before the INSERT.

    A failed attempt does not produce a batch row, so the application
    service must NOT call :meth:`upsert_many` on the
    :class:`invest_domain.market_data.models.ProviderBatch` returned
    from a failed ``ProviderAttempt``. The pipeline asset enforces this
    by gating ``upsert_etf_daily_bars`` on the attempt status.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _next_revision(
        self,
        *,
        instrument_id: UUID,
        trade_date: date,
        adjustment: Adjust,
    ) -> int:
        """Return the next ``revision`` number for the given logical key.

        The lookup is scoped to the current session so the read sees
        any rows added by :meth:`upsert_many` earlier in the same
        transaction (identity-map behaviour). Returns ``1`` when no
        row exists for the logical key.
        """

        current_max = self._session.execute(
            select(func.max(DailyBarRow.revision)).where(
                DailyBarRow.instrument_id == instrument_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
            )
        ).scalar()
        return 1 if current_max is None else int(current_max) + 1

    def get_latest(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        trade_date: date,
        adjustment: Adjust,
    ) -> StoredDailyBar | None:
        """Return the row with the highest ``revision`` for the logical key.

        Per ADR-0006 §6 this is the recommended read surface for new
        snapshot builders. The caller may also use
        :meth:`get_exact` to pin a specific revision for replay.
        """

        raw_id = (
            instrument_id.value
            if isinstance(instrument_id, InstrumentId)
            else instrument_id
        )
        row = self._session.execute(
            select(DailyBarRow)
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
            )
            .order_by(DailyBarRow.revision.desc())
            .limit(1)
        ).scalar_one_or_none()
        return _row_to_stored_daily_bar(row) if row is not None else None

    def get_exact(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        trade_date: date,
        adjustment: Adjust,
        revision: int,
    ) -> StoredDailyBar | None:
        """Return the row at the exact ``revision`` for the logical key."""

        if revision < 1:
            raise ValueError(f"revision must be >= 1, got {revision}")
        raw_id = (
            instrument_id.value
            if isinstance(instrument_id, InstrumentId)
            else instrument_id
        )
        row = self._session.execute(
            select(DailyBarRow)
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date == trade_date,
                DailyBarRow.adjustment == adjustment.value,
                DailyBarRow.revision == revision,
            )
            .limit(1)
        ).scalar_one_or_none()
        return _row_to_stored_daily_bar(row) if row is not None else None

    def list_by_instrument_and_range(
        self,
        *,
        instrument_id: UUID | InstrumentId,
        start_date: date,
        end_date: date,
        adjustment: Adjust,
    ) -> Sequence[StoredDailyBar]:
        """Return every revision of the bars in ``[start_date, end_date]``.

        The result includes all revisions of the matching
        ``(instrument_id, trade_date, adjustment)`` triplets, ordered
        by ``trade_date`` then ``revision`` ascending so the caller can
        group revisions in a single pass. :class:`Market` use cases
        that need "the latest revision per day" should feed the result
        through :meth:`get_latest` (per ADR-0006 §5); candidate-pool
        replay MUST NOT use this list directly.
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        raw_id = (
            instrument_id.value
            if isinstance(instrument_id, InstrumentId)
            else instrument_id
        )
        rows = self._session.execute(
            select(DailyBarRow)
            .where(
                DailyBarRow.instrument_id == raw_id,
                DailyBarRow.trade_date >= start_date,
                DailyBarRow.trade_date <= end_date,
                DailyBarRow.adjustment == adjustment.value,
            )
            .order_by(
                DailyBarRow.trade_date.asc(),
                DailyBarRow.revision.asc(),
            )
        ).scalars().all()
        return [_row_to_stored_daily_bar(row) for row in rows]

    def upsert_many(self, bars: Sequence[NewDailyBar | DailyBar]) -> list[StoredDailyBar]:
        """Persist ``bars`` into ``core.daily_bars`` under ADR-0006 revision rules.

        The algorithm follows ADR-0006 §3:

        - For each bar, look up the latest persisted row for the
          ``(instrument_id, trade_date, adjustment)`` logical key.
        - If no row exists, insert with ``revision = 1``.
        - If a row exists and its ``row_hash`` equals the incoming
          ``row_hash``, skip — the re-collect is a no-op at the core
          layer, only the ``raw.provider_batches`` audit row is added.
        - If a row exists and the hashes differ, insert with
          ``revision = latest + 1``.

        Returns the list of rows actually written (rows whose content
        matched the latest revision are NOT in the result). The order
        of the returned list mirrors the input order so callers can
        correlate ``upsert_many`` invocations with the original
        Provider batch.
        """

        if not bars:
            return []

        written: list[StoredDailyBar] = []
        for bar in bars:
            (instrument_id, trade_date, adjustment, payload) = _normalise_bar(bar)
            latest = self.get_latest(
                instrument_id=instrument_id,
                trade_date=trade_date,
                adjustment=adjustment,
            )
            if latest is not None and latest.row_hash == payload["row_hash"]:
                continue
            next_revision = self._next_revision(
                instrument_id=instrument_id,
                trade_date=trade_date,
                adjustment=adjustment,
            )
            row = DailyBarRow(
                id=uuid.uuid4(),
                instrument_id=instrument_id,
                trade_date=trade_date,
                open=payload["open"],
                high=payload["high"],
                low=payload["low"],
                close=payload["close"],
                prev_close=payload["prev_close"],
                volume=payload["volume"],
                amount=payload["amount"],
                adjustment=adjustment.value,
                trading_status=payload["trading_status"],
                source_provider=payload["source_provider"],
                source_batch_id=payload["source_batch_id"],
                observed_at=payload["observed_at"],
                revision=next_revision,
                row_hash=payload["row_hash"],
            )
            self._session.add(row)
            self._session.flush()
            written.append(_row_to_stored_daily_bar(row))
        return written


def _normalise_bar(
    bar: NewDailyBar | DailyBar,
) -> tuple[UUID, date, Adjust, dict[str, Any]]:
    """Reduce the input ``bar`` to a canonical ``(id, date, adjust, payload)`` tuple.

    The repository accepts either the domain :class:`DailyBar` (full
    validation already done) or a transport-shape :class:`NewDailyBar`
    straight from the application service. The ``payload`` is the
    keyword-argument shape that the row builder consumes.
    """

    if isinstance(bar, DailyBar):
        return (
            bar.instrument_id.value,
            bar.trade_date,
            bar.adjustment,
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "prev_close": bar.prev_close,
                "volume": bar.volume,
                "amount": bar.amount,
                "trading_status": bar.trading_status.value,
                "source_provider": bar.source.provider_key,
                "source_batch_id": bar.source.source_batch_id,
                "observed_at": bar.source.observed_at,
                "row_hash": bar.compute_row_hash(),
            },
        )
    if isinstance(bar, NewDailyBar):
        return (
            bar.instrument_id,
            bar.trade_date,
            bar.adjustment,
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "prev_close": bar.prev_close,
                "volume": bar.volume,
                "amount": bar.amount,
                "trading_status": bar.trading_status.value,
                "source_provider": bar.source_provider,
                "source_batch_id": bar.source_batch_id,
                "observed_at": bar.observed_at,
                "row_hash": bar.row_hash,
            },
        )
    raise TypeError(
        "upsert_many accepts invest_domain.market_data.models.DailyBar or "
        "invest_storage.repositories.NewDailyBar, "
        f"got {type(bar).__name__}"
    )


def _row_to_stored_daily_bar(row: DailyBarRow) -> StoredDailyBar:
    return StoredDailyBar(
        id=row.id,
        instrument_id=row.instrument_id,
        trade_date=row.trade_date,
        open=_as_decimal(row.open),
        high=_as_decimal(row.high),
        low=_as_decimal(row.low),
        close=_as_decimal(row.close),
        prev_close=_as_decimal(row.prev_close),
        volume=_as_decimal(row.volume),
        amount=_as_decimal(row.amount),
        adjustment=row.adjustment,
        trading_status=row.trading_status,
        source_provider=row.source_provider,
        source_batch_id=row.source_batch_id,
        observed_at=row.observed_at,
        revision=row.revision,
        row_hash=row.row_hash,
        created_at=row.created_at,
    )


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _excluded_set() -> dict[str, Any]:
    excluded = insert(InstrumentRow).excluded
    return {
        "symbol": excluded.symbol,
        "exchange": excluded.exchange,
        "name": excluded.name,
        "instrument_type": excluded.instrument_type,
        "currency": excluded.currency,
        "list_date": excluded.list_date,
        "delist_date": excluded.delist_date,
        "status": excluded.status,
        "underlying_index": excluded.underlying_index,
        "category": excluded.category,
        "provider_symbol_map": excluded.provider_symbol_map,
        "valid_from": excluded.valid_from,
        "valid_to": excluded.valid_to,
        "is_active": excluded.is_active,
    }


def _row_to_instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        symbol=row.symbol,
        name=row.name,
        exchange=row.exchange,
        instrument_type=InstrumentType(row.instrument_type),
        is_active=row.is_active,
        instrument_id=InstrumentId(row.id) if row.id is not None else None,
        currency=Currency(row.currency) if row.currency else Currency.CNY,
        list_date=_as_date(row.list_date),
        delist_date=_as_date(row.delist_date),
        status=InstrumentStatus(row.status) if row.status else InstrumentStatus.UNKNOWN,
        underlying_index=row.underlying_index,
        category=row.category,
        provider_symbol_map=dict(row.provider_symbol_map or {}),
        valid_from=_as_date(row.valid_from),
        valid_to=_as_date(row.valid_to),
    )


class InputSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: InputSnapshot) -> InputSnapshot:
        statement = (
            insert(InputSnapshotRow)
            .values(
                id=snapshot.id,
                snapshot_date=snapshot.snapshot_date,
                instrument_ids=[str(value) for value in snapshot.instrument_ids],
                content_hash=snapshot.content_hash,
                row_count=snapshot.row_count,
                created_at=snapshot.created_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_input_snapshots_date_hash",
            )
            .returning(InputSnapshotRow.id)
        )
        inserted_id = self._session.execute(statement).scalar_one_or_none()
        if inserted_id is not None:
            return snapshot

        existing = self.get_by_date_and_hash(
            snapshot.snapshot_date,
            snapshot.content_hash,
        )
        if existing is None:
            raise RuntimeError(
                "input snapshot insert conflicted but the existing row was not found"
            )
        return existing

    def get_by_date_and_hash(
        self,
        snapshot_date: date,
        content_hash: str,
    ) -> InputSnapshot | None:
        stmt = (
            select(InputSnapshotRow)
            .where(
                InputSnapshotRow.snapshot_date == snapshot_date,
                InputSnapshotRow.content_hash == content_hash,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_input_snapshot(row) if row is not None else None

    def list_by_date(self, snapshot_date: date) -> list[InputSnapshot]:
        rows = self._session.scalars(
            select(InputSnapshotRow)
            .where(InputSnapshotRow.snapshot_date == snapshot_date)
            .order_by(
                InputSnapshotRow.created_at.asc(),
                InputSnapshotRow.id.asc(),
            )
        ).all()
        return [_row_to_input_snapshot(row) for row in rows]


def _row_to_input_snapshot(row: InputSnapshotRow) -> InputSnapshot:
    return InputSnapshot(
        id=row.id,
        snapshot_date=row.snapshot_date,
        instrument_ids=tuple(
            value if isinstance(value, UUID) else UUID(str(value))
            for value in row.instrument_ids
        ),
        content_hash=row.content_hash,
        row_count=row.row_count,
        created_at=row.created_at,
    )


class SqlAlchemyPipelineRunRepository:
    """Read/write access to ``ops.pipeline_runs``.

    The repository never commits: it only mutates the session, and the
    surrounding :class:`invest_storage.unit_of_work.SqlAlchemyUnitOfWork`
    owns the transaction boundary. All public methods return the
    domain-side :class:`invest_domain.pipeline.PipelineRun` rather than
    the SQLAlchemy ORM row so callers can stay free of storage
    machinery.

    The repository treats :meth:`start` as the transition into the
    ``running`` state regardless of the input status; the application
    layer is expected to hand in a fully-formed :class:`PipelineRun`
    and rely on the repository to assign the storage-side identity and
    the lifecycle timestamps.
    """

    _START_STATUS = PipelineRunStatus.RUNNING.value

    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, run: PipelineRun) -> PipelineRun:
        """Insert a new ``pipeline_runs`` row in the ``running`` state.

        The input ``run`` is taken as the canonical payload for
        ``job_key``, ``trigger_type``, ``algorithm_version`` and ``started_at``;
        ``status`` is overwritten with ``"running"`` and a fresh UUID is
        generated in Python. ``error_summary`` is reset to ``None`` so
        a re-used domain value cannot leak a stale failure message into
        a brand-new run.

        Returns the persisted :class:`PipelineRun` carrying the
        assigned UUID and the server-generated ``created_at`` /
        ``updated_at`` timestamps.
        """

        row = PipelineRunRow(
            id=uuid.uuid4(),
            dagster_run_id=run.dagster_run_id,
            job_key=run.job_key,
            partition_key=run.partition_key,
            trigger_type=run.trigger_type,
            algorithm_version=run.algorithm_version,
            config_snapshot=run.config_snapshot or {},
            status=self._START_STATUS,
            started_at=run.started_at,
            finished_at=None,
            error_summary=None,
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_pipeline_run(row)

    def mark_succeeded(
        self, run_id: UUID, *, finished_at: datetime
    ) -> PipelineRun:
        """Transition a run into the ``succeeded`` terminal state.

        Updates ``status='succeeded'`` and ``finished_at``; ``error_summary``
        is reset to ``None`` so a previous transient failure is not
        carried forward.
        """

        row = self._session.get(PipelineRunRow, run_id)
        if row is None:
            raise LookupError(
                f"PipelineRun {run_id!s} not found; cannot mark succeeded"
            )
        row.status = PipelineRunStatus.SUCCEEDED.value
        row.finished_at = finished_at
        row.error_summary = None
        self._session.flush()
        return _row_to_pipeline_run(row)

    def mark_failed(
        self, run_id: UUID, *, error: str, finished_at: datetime
    ) -> PipelineRun:
        """Transition a run into the ``failed`` terminal state.

        Updates ``status='failed'``, ``finished_at`` and ``error_summary``.
        Raises :class:`ValueError` when ``error`` is empty so the
        repository never writes a meaningless failure record.
        """

        if not isinstance(error, str) or not error.strip():
            raise ValueError(
                "SqlAlchemyPipelineRunRepository.mark_failed requires a "
                "non-empty error message"
            )
        row = self._session.get(PipelineRunRow, run_id)
        if row is None:
            raise LookupError(
                f"PipelineRun {run_id!s} not found; cannot mark failed"
            )
        row.status = PipelineRunStatus.FAILED.value
        row.finished_at = finished_at
        row.error_summary = error
        self._session.flush()
        return _row_to_pipeline_run(row)

    def get_by_id(self, run_id: UUID) -> PipelineRun | None:
        """Return the run for ``run_id`` or ``None`` if absent."""

        row = self._session.get(PipelineRunRow, run_id)
        return _row_to_pipeline_run(row) if row is not None else None

    def list_recent(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[PipelineRun]:
        """Return runs ordered by ``started_at`` descending.

        The descending ``started_at`` order matches the dashboard use
        case where the most recent run must come first; ties on
        ``started_at`` (e.g. two runs scheduled for the same instant)
        are broken by ``id`` so the result is stable.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(PipelineRunRow)
            .order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_pipeline_run(row) for row in rows]

    def count_by_status(self, status: str) -> int:
        """Return the number of runs in the given ``status``.

        ``status`` is taken as a raw string so callers can drive the
        count with the canonical lowercase vocabulary without having
        to construct a :class:`PipelineRunStatus`. An unknown value
        yields zero rather than raising so the repository can be
        probed safely from operational dashboards.
        """

        stmt = (
            select(PipelineRunRow.id)
            .where(PipelineRunRow.status == status)
        )
        return len(self._session.scalars(stmt).all())


def _row_to_pipeline_run(row: PipelineRunRow) -> PipelineRun:
    return PipelineRun(
        id=row.id,
        dagster_run_id=row.dagster_run_id,
        job_key=row.job_key,
        partition_key=row.partition_key,
        trigger_type=row.trigger_type,
        algorithm_version=row.algorithm_version,
        config_snapshot=dict(row.config_snapshot or {}),
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=row.error_summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_stored_request(row: ProviderRequestRow) -> StoredProviderRequest:
    return StoredProviderRequest(
        id=row.id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        request_key=row.request_key,
        request_params=dict(row.request_params or {}),
        requested_by_run_id=row.requested_by_run_id,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _row_to_stored_attempt(row: ProviderAttemptRow) -> StoredProviderAttempt:
    return StoredProviderAttempt(
        id=row.id,
        provider_request_id=row.provider_request_id,
        attempt_no=row.attempt_no,
        provider_request_id_text=row.provider_request_id_text,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,
        http_status=row.http_status,
        error_stage=row.error_stage,
        error_code=row.error_code,
        error_message=row.error_message,
        response_payload_sha256=row.response_payload_sha256,
        response_payload_json=row.response_payload_json,
        response_payload_uri=row.response_payload_uri,
        created_at=row.created_at,
    )


def _row_to_stored_batch(row: RawProviderBatchRow) -> StoredProviderBatch:
    return StoredProviderBatch(
        id=row.id,
        provider_request_id=row.provider_request_id,
        provider_attempt_id=row.provider_attempt_id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        record_count=row.record_count,
        payload_sha256=row.payload_sha256,
        warnings=list(row.warnings or []),
        status=row.status,
        created_at=row.created_at,
    )


class SqlAlchemyCandidatePoolRunRepository:
    """Read/write access to ``analytics.candidate_pool_runs``.

    The repository owns persistence but never the state-machine
    semantics: every transition flows through the domain method
    :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`
    so that illegal ``CALCULATED -> PUBLISHED`` etc. attempts are
    rejected by the domain, not the database. The repository only
    translates the resulting :class:`CandidatePoolRun` into a row update.

    The natural unique key
    ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
    input_snapshot_id)`` is enforced by the database; duplicate inserts
    surface as :class:`sqlalchemy.exc.IntegrityError`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        run: CandidatePoolRun,
        *,
        quality_summary: dict[str, Any] | None = None,
    ) -> CandidatePoolRun:
        """Persist a brand-new ``calculated`` run.

        The input ``run`` must already be in the ``CALCULATED`` state;
        :meth:`transition_status` is the only path to the terminal
        states. ``quality_summary`` is an opaque JSONB blob for the
        storage layer; the domain ``CandidatePoolRun`` does not carry
        it, so it is supplied here out-of-band. ``started_at`` defaults
        to ``run.created_at`` so the two timestamps stay aligned when
        the application does not pass an explicit value.
        """

        if run.status is not CandidatePoolStatus.CALCULATED:
            raise ValueError(
                "SqlAlchemyCandidatePoolRunRepository.add requires the run to "
                f"be in CALCULATED state, got {run.status.value!r}"
            )
        row = CandidatePoolRunRow(
            id=run.id,
            trade_date=run.trade_date,
            algorithm_key=run.algorithm_key,
            algorithm_version=run.algorithm_version,
            parameter_set_key=run.parameter_set_key,
            parameter_hash=run.parameter_hash,
            input_snapshot_id=run.input_snapshot_id,
            input_row_count=run.input_row_count,
            included_count=run.included_count,
            status=run.status.value,
            started_at=run.created_at,
            finished_at=run.finished_at,
            published_at=run.published_at,
            rejected_at=run.rejected_at,
            rejection_reason=run.rejection_reason,
            quality_summary=dict(quality_summary) if quality_summary else {},
        )
        self._session.add(row)
        self._session.flush()
        return _row_to_candidate_pool_run(row)

    def get_by_id(self, run_id: UUID) -> CandidatePoolRun | None:
        """Return the run with ``run_id`` or ``None`` if absent."""

        row = self._session.get(CandidatePoolRunRow, run_id)
        return _row_to_candidate_pool_run(row) if row is not None else None

    def get_by_natural_key(
        self,
        *,
        trade_date: date,
        algorithm_key: str,
        algorithm_version: str,
        parameter_hash: str,
        input_snapshot_id: UUID,
    ) -> CandidatePoolRun | None:
        """Return the run identified by the ADR-0008 natural unique key.

        The natural key
        ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
        input_snapshot_id)`` is enforced by the database unique constraint
        ``uq_candidate_pool_runs_natural_key``; at most one row can match.
        This lookup is the idempotent entry point used by the application
        service when the same business calculation is rerun so the existing
        ``PUBLISHED`` run can be returned instead of triggering a duplicate
        insert.
        """

        stmt = (
            select(CandidatePoolRunRow)
            .where(
                CandidatePoolRunRow.trade_date == trade_date,
                CandidatePoolRunRow.algorithm_key == algorithm_key,
                CandidatePoolRunRow.algorithm_version == algorithm_version,
                CandidatePoolRunRow.parameter_hash == parameter_hash,
                CandidatePoolRunRow.input_snapshot_id == input_snapshot_id,
            )
            .limit(1)
        )
        row = self._session.scalars(stmt).first()
        return _row_to_candidate_pool_run(row) if row is not None else None

    def list_by_status(
        self,
        status: CandidatePoolStatus | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CandidatePoolRun]:
        """Return runs in ``status`` ordered by ``trade_date`` desc then ``id`` asc.

        The descending ``trade_date`` order matches the dashboard use
        case where the most recent trade-day must come first. An
        unknown ``status`` value yields an empty result rather than
        raising so the repository can be probed safely.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        status_value = (
            status.value if isinstance(status, CandidatePoolStatus) else str(status)
        )
        stmt = (
            select(CandidatePoolRunRow)
            .where(CandidatePoolRunRow.status == status_value)
            .order_by(
                CandidatePoolRunRow.trade_date.desc(),
                CandidatePoolRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_run(row) for row in rows]

    def list_by_trade_date(
        self,
        trade_date: date,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CandidatePoolRun]:
        """Return runs for ``trade_date`` ordered by ``created_at`` desc then ``id`` asc.

        The descending ``created_at`` order surfaces the latest run
        for the trade-day first; ties on ``created_at`` (e.g. two
        runs scheduled for the same instant) are broken by ``id`` so
        the result is stable.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(CandidatePoolRunRow)
            .where(CandidatePoolRunRow.trade_date == trade_date)
            .order_by(
                CandidatePoolRunRow.created_at.desc(),
                CandidatePoolRunRow.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_run(row) for row in rows]

    def transition_status(
        self,
        run_id: UUID,
        new_status: CandidatePoolStatus,
        *,
        at: datetime | None = None,
        rejection_reason: str | None = None,
    ) -> CandidatePoolRun:
        """Persist a state-machine transition.

        The current row is loaded, the domain
        :meth:`CandidatePoolRun.transition_to` is invoked to enforce
        the legal transition graph, and the resulting
        :class:`CandidatePoolRun` is written back. ``at`` is the
        timezone-aware UTC timestamp for terminal-state transitions
        (``PUBLISHED`` / ``REJECTED``); ``rejection_reason`` is required
        by the domain invariant when transitioning to ``REJECTED``.
        """

        row = self._session.get(CandidatePoolRunRow, run_id)
        if row is None:
            raise LookupError(
                f"CandidatePoolRun {run_id!s} not found; cannot transition status"
            )
        current = _row_to_candidate_pool_run(row)
        transitioned = current.transition_to(
            new_status, at=at, rejection_reason=rejection_reason
        )
        row.status = transitioned.status.value
        row.published_at = transitioned.published_at
        row.rejected_at = transitioned.rejected_at
        row.rejection_reason = transitioned.rejection_reason
        if transitioned.finished_at is not None:
            row.finished_at = transitioned.finished_at
        elif new_status is CandidatePoolStatus.VALIDATED:
            row.finished_at = at if at is not None else datetime.now(tz=UTC)
        self._session.flush()
        return _row_to_candidate_pool_run(row)


class SqlAlchemyCandidatePoolItemRepository:
    """Read/write access to ``analytics.candidate_pool_items``.

    One row per ``(run_id, instrument_id)`` pair; the composite primary
    key is enforced by the database. Items are persisted in bulk via
    :meth:`bulk_add` so a full result set is written with a single
    ``INSERT`` round-trip.

    The JSONB columns ``metrics``, ``rule_results`` and
    ``exclusion_reasons`` are JSON-encoded using the
    :mod:`invest_storage.repositories` helpers so the storage layer
    stays free of domain-specific value objects.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def bulk_add(
        self,
        run_id: UUID,
        items: Sequence[CandidatePoolItem],
    ) -> int:
        """Persist every ``items`` entry against ``run_id``.

        Returns the number of rows actually inserted. The database
        rejects duplicate ``(run_id, instrument_id)`` pairs with
        :class:`sqlalchemy.exc.IntegrityError` so the caller can rely
        on a single, deterministic bulk-insert contract.
        """

        if not items:
            return 0
        rows = [
            CandidatePoolItemRow(
                id=uuid.uuid4(),
                run_id=run_id,
                instrument_id=item.instrument_id.value,
                included=item.included,
                rank=item.rank,
                total_score=item.total_score,
                metrics=_metrics_to_json(item.metrics),
                rule_results=[_rule_outcome_to_json(r) for r in item.rule_results],
                exclusion_reasons=[
                    _exclusion_reason_to_json(r) for r in item.exclusion_reasons
                ],
            )
            for item in items
        ]
        self._session.add_all(rows)
        self._session.flush()
        return len(rows)

    def list_by_run_id(
        self,
        run_id: UUID,
        *,
        limit: int = 10_000,
        offset: int = 0,
    ) -> Sequence[CandidatePoolItem]:
        """Return the items for ``run_id`` ordered by ``included`` desc then ``rank`` asc.

        Included items (rank > 0) come first, ordered by ascending
        rank; excluded items follow in ``created_at`` ascending order.
        The composite primary key ``(run_id, instrument_id)`` is the
        natural tiebreaker for excluded items where no rank is set.
        """

        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        stmt = (
            select(CandidatePoolItemRow)
            .where(CandidatePoolItemRow.run_id == run_id)
            .order_by(
                CandidatePoolItemRow.included.desc(),
                CandidatePoolItemRow.rank.asc().nulls_last(),
                CandidatePoolItemRow.instrument_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.scalars(stmt).all()
        return [_row_to_candidate_pool_item(row) for row in rows]


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise TypeError(f"expected date or None, got {type(value).__name__}")


def _currency_value(value: Currency) -> str:
    return value.value if isinstance(value, Currency) else str(value)


def _status_value(value: InstrumentStatus) -> str:
    return value.value if isinstance(value, InstrumentStatus) else str(value)


def _provider_symbol_map(value: dict[str, str] | None) -> dict[str, str]:
    return dict(value) if value else {}


def _row_to_candidate_pool_run(row: CandidatePoolRunRow) -> CandidatePoolRun:
    return CandidatePoolRun(
        id=row.id,
        trade_date=row.trade_date,
        algorithm_key=row.algorithm_key,
        algorithm_version=row.algorithm_version,
        parameter_set_key=row.parameter_set_key,
        parameter_hash=row.parameter_hash,
        input_snapshot_id=row.input_snapshot_id,
        input_row_count=row.input_row_count,
        included_count=row.included_count,
        status=CandidatePoolStatus(row.status),
        created_at=row.started_at,
        finished_at=row.finished_at,
        published_at=row.published_at,
        rejected_at=row.rejected_at,
        rejection_reason=row.rejection_reason,
    )


def _row_to_candidate_pool_item(row: CandidatePoolItemRow) -> CandidatePoolItem:
    metrics = _metrics_from_json(row.metrics)
    rule_results = tuple(
        _rule_outcome_from_json(entry) for entry in (row.rule_results or [])
    )
    exclusion_reasons = tuple(
        _exclusion_reason_from_json(entry) for entry in (row.exclusion_reasons or [])
    )
    return CandidatePoolItem(
        instrument_id=InstrumentId(row.instrument_id),
        included=row.included,
        rank=row.rank,
        total_score=(
            Decimal(row.total_score) if row.total_score is not None else None
        ),
        metrics=metrics,
        rule_results=rule_results,
        exclusion_reasons=exclusion_reasons,
    )


def _metrics_to_json(metrics: Any) -> dict[str, str]:
    """Encode ``metrics`` (Mapping[str, Decimal]) as JSONB-compatible dict[str, str].

    Decimals are serialised as strings to preserve precision through
    JSON; the JSON loader parses them back with
    :func:`_metrics_from_json`.
    """

    if not metrics:
        return {}
    result: dict[str, str] = {}
    for key, value in dict(metrics).items():
        if isinstance(value, Decimal):
            result[str(key)] = format(value, "f")
        else:
            result[str(key)] = str(value)
    return result


def _metrics_from_json(value: Any) -> dict[str, Decimal]:
    """Decode a JSONB ``metrics`` blob into Mapping[str, Decimal]."""

    if not value:
        return {}
    return {str(key): Decimal(str(entry)) for key, entry in dict(value).items()}


def _rule_outcome_to_json(outcome: RuleOutcome) -> dict[str, Any]:
    """Encode a :class:`RuleOutcome` as a JSONB-compatible dict."""

    payload: dict[str, Any] = {
        "rule_key": outcome.rule_key,
        "passed": outcome.passed,
        "severity": outcome.severity.value,
    }
    if outcome.value is not None:
        payload["value"] = format(outcome.value, "f")
    if outcome.threshold is not None:
        payload["threshold"] = format(outcome.threshold, "f")
    if outcome.message is not None:
        payload["message"] = outcome.message
    return payload


def _rule_outcome_from_json(value: Any) -> RuleOutcome:
    """Decode a JSONB-encoded rule outcome into a :class:`RuleOutcome`."""

    if not isinstance(value, dict):
        raise TypeError(
            f"rule_results entry must be a dict, got {type(value).__name__}"
        )
    rule_key = value.get("rule_key")
    if not rule_key:
        raise ValueError("rule_results entry missing non-empty 'rule_key'")
    passed = bool(value.get("passed"))
    severity = RuleSeverity(str(value.get("severity", RuleSeverity.ERROR.value)))
    raw_value = value.get("value")
    raw_threshold = value.get("threshold")
    return RuleOutcome(
        rule_key=str(rule_key),
        passed=passed,
        severity=severity,
        value=Decimal(str(raw_value)) if raw_value is not None else None,
        threshold=Decimal(str(raw_threshold)) if raw_threshold is not None else None,
        message=value.get("message"),
    )


def _exclusion_reason_to_json(reason: ExclusionReason) -> dict[str, str]:
    return {"code": reason.code, "message": reason.message}


def _exclusion_reason_from_json(value: Any) -> ExclusionReason:
    if not isinstance(value, dict):
        raise TypeError(
            f"exclusion_reasons entry must be a dict, got {type(value).__name__}"
        )
    code = value.get("code")
    message = value.get("message")
    if not code:
        raise ValueError("exclusion_reasons entry missing non-empty 'code'")
    if not message:
        raise ValueError("exclusion_reasons entry missing non-empty 'message'")
    return ExclusionReason(code=str(code), message=str(message))