"""Unit-of-Work protocol and SQLAlchemy implementation.

A UnitOfWork (UoW) wraps a single SQLAlchemy ``Session`` plus the
repositories that operate against it. The application layer enters the
UoW, mutates rows through the repository properties, then either commits
or rolls back - the UoW owns the transaction boundary.

Design constraints (see M1 increment 3 plan):

- ``commit()`` / ``rollback()`` mirror the underlying ``Session`` API.
- The UoW is a context manager: ``__enter__`` returns ``self``,
  ``__exit__`` commits on clean exit and rolls back on exception, then
  closes the session.
- Repositories are exposed as cached properties: ``uow.instruments``,
  ``uow.provider_requests``, ``uow.provider_attempts``,
  ``uow.provider_batches``, ``uow.pipeline_runs``,
  ``uow.candidate_pool_runs`` and ``uow.candidate_pool_items``. The
  same repository instance is reused for the lifetime of the UoW so
  identity-based caching (e.g. SQLAlchemy's identity map) works as
  expected.
- The protocol (``UnitOfWork``) keeps the application layer decoupled
  from SQLAlchemy; the SQLAlchemy implementation
  (:class:`SqlAlchemyUnitOfWork`) is the only adapter in M1.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session, sessionmaker

from invest_storage.repositories import (
    InputSnapshotRepository,
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyDailyBarRepository,
    SqlAlchemyEtfProfileRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyPipelineRunRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
)


@runtime_checkable
class InstrumentRepositoryPort(Protocol):
    """Subset of the Instrument repository surface the UoW exposes.

    Defined as a Protocol so callers can type-hint against it without
    importing the SQLAlchemy implementation. The Protocol is deliberately
    structural: any object that implements the methods satisfies it.
    """

    def upsert_many(self, instruments): ...
    def get_by_id(self, instrument_id): ...
    def get_many_by_ids(self, instrument_ids): ...
    def get_by_business_key(self, *, exchange: str, symbol: str): ...
    def list_active(self, *, limit: int = 100, offset: int = 0): ...
    def count_active(self) -> int: ...


@runtime_checkable
class InputSnapshotRepositoryPort(Protocol):
    def add(self, snapshot): ...
    def get_by_date_and_hash(self, snapshot_date, content_hash): ...
    def list_by_date(self, snapshot_date): ...


@runtime_checkable
class ProviderRequestRepositoryPort(Protocol):
    """Subset of the ProviderRequest repository surface the UoW exposes."""

    def add(self, request): ...
    def get_by_id(self, request_id): ...
    def get_by_logical_key(
        self, *, provider_key: str, dataset_key: str, request_key: str
    ): ...
    def get_or_create(self, request): ...
    def mark_status(
        self, request_id, *, status: str, completed_at=None
    ): ...


@runtime_checkable
class ProviderAttemptRepositoryPort(Protocol):
    """Subset of the ProviderAttempt repository surface the UoW exposes."""

    def add(self, attempt): ...
    def start(
        self,
        *,
        provider_request_id,
        attempt_no: int,
        started_at,
        provider_request_id_text=None,
    ): ...
    def mark_succeeded(
        self,
        attempt_id,
        *,
        finished_at,
        response_payload_sha256: str,
        response_payload_json=None,
        response_payload_uri=None,
        http_status=None,
    ): ...
    def mark_failed(
        self,
        attempt_id,
        *,
        finished_at,
        error_stage: str,
        error_code: str,
        error_message=None,
        http_status=None,
    ): ...
    def get_by_id(self, attempt_id): ...
    def list_by_request(self, request_id, *, limit: int = 100, offset: int = 0): ...


@runtime_checkable
class ProviderBatchRepositoryPort(Protocol):
    """Subset of the ProviderBatch repository surface the UoW exposes."""

    def add(self, batch): ...
    def get_by_id(self, batch_id): ...
    def list_by_attempt(self, attempt_id, *, limit: int = 10, offset: int = 0): ...
    def list_by_provider_dataset(
        self, *, provider_key: str, dataset_key: str, limit: int = 100, offset: int = 0
    ): ...


@runtime_checkable
class PipelineRunRepositoryPort(Protocol):
    """Subset of the PipelineRun repository surface the UoW exposes."""

    def start(self, run): ...
    def mark_succeeded(self, run_id, *, finished_at): ...
    def mark_failed(self, run_id, *, error: str, finished_at): ...
    def get_blocking_by_job_and_partition(
        self, *, job_key: str, partition_key: str | None
    ): ...
    def get_by_id(self, run_id): ...
    def list_recent(self, *, limit: int = 50, offset: int = 0): ...
    def count_by_status(self, status: str) -> int: ...


@runtime_checkable
class CandidatePoolRunRepositoryPort(Protocol):
    """Subset of the CandidatePoolRun repository surface the UoW exposes."""

    def add(self, run, *, quality_summary=None): ...
    def get_by_id(self, run_id): ...
    def get_by_natural_key(
        self,
        *,
        trade_date,
        algorithm_key: str,
        algorithm_version: str,
        parameter_hash: str,
        input_snapshot_id,
    ): ...
    def list_by_status(self, status, *, limit: int = 100, offset: int = 0): ...
    def list_by_trade_date(self, trade_date, *, limit: int = 100, offset: int = 0): ...
    def transition_status(
        self,
        run_id,
        new_status,
        *,
        at=None,
        rejection_reason=None,
    ): ...


@runtime_checkable
class CandidatePoolItemRepositoryPort(Protocol):
    """Subset of the CandidatePoolItem repository surface the UoW exposes."""

    def bulk_add(self, run_id, items): ...
    def list_by_run_id(self, run_id, *, limit: int = 10_000, offset: int = 0): ...


@runtime_checkable
class DailyBarRepositoryPort(Protocol):
    """Subset of the DailyBar repository surface the UoW exposes.

    The :class:`invest_storage.repositories.SqlAlchemyDailyBarRepository`
    is the only adapter in M1; the Protocol keeps the application
    layer decoupled from the concrete class. ``upsert_many`` is the
    only write path so callers cannot bypass the ADR-0006 revision
    comparison; ``get_latest`` and ``get_exact`` mirror the
    snapshot-vs-replay split called out in ADR-0006 §6.
    """

    def upsert_many(self, bars): ...
    def get_latest(
        self, *, instrument_id, trade_date, adjustment
    ): ...
    def get_exact(
        self, *, instrument_id, trade_date, adjustment, revision: int
    ): ...
    def list_by_instrument_and_range(
        self, *, instrument_id, start_date, end_date, adjustment
    ): ...
    def list_latest_by_instrument_and_range(
        self, *, instrument_id, start_date, end_date, adjustment
    ): ...
    def list_latest_by_instruments_and_range(
        self, *, instrument_ids, start_date, end_date, adjustment
    ): ...


@runtime_checkable
class EtfProfileRepositoryPort(Protocol):
    """Subset of the EtfProfile repository surface the UoW exposes.

    Stage DC-2 introduces ``core.etf_profiles`` and the
    ``SqlAlchemyEtfProfileRepository`` that wraps it; the Protocol
    mirrors the same public surface so application code can type-hint
    against ``uow.etf_profiles`` without importing the SQLAlchemy
    adapter. ``upsert`` is the idempotent write path keyed on
    ``instrument_id``; ``get_by_id``, ``list_by_manager``,
    ``list_by_category``, ``list_by_fund_type`` and ``list_all`` are
    the read paths needed by the Stage DC-2 dashboards.
    """

    def upsert(self, profile): ...
    def get_by_id(self, instrument_id): ...
    def list_by_manager(self, manager, *, limit: int = 100, offset: int = 0): ...
    def list_by_category(self, category, *, limit: int = 100, offset: int = 0): ...
    def list_by_fund_type(self, fund_type, *, limit: int = 100, offset: int = 0): ...
    def list_all(self, *, limit: int = 100, offset: int = 0): ...
    def count_all(self) -> int: ...


@runtime_checkable
class SessionProvider(Protocol):
    """Anything that can hand out a SQLAlchemy ``Session``.

    The default implementation is the ``sessionmaker`` returned by
    :func:`invest_storage.database.session_factory`. The protocol lets
    the UnitOfWork be constructed against a fake provider in unit tests
    of the UoW itself, without spinning up a real database.
    """

    def __call__(self) -> Session:
        ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Storage-layer transactional context.

    The application layer interacts with a UoW through its repository
    properties and :meth:`commit` / :meth:`rollback`. The
    ``with uow:`` form is preferred because it handles commit/rollback/
    close automatically based on whether the block raised.
    """

    instruments: InstrumentRepositoryPort
    input_snapshot_repository: InputSnapshotRepositoryPort
    provider_requests: ProviderRequestRepositoryPort
    provider_attempts: ProviderAttemptRepositoryPort
    provider_batches: ProviderBatchRepositoryPort
    pipeline_runs: PipelineRunRepositoryPort
    candidate_pool_runs: CandidatePoolRunRepositoryPort
    candidate_pool_items: CandidatePoolItemRepositoryPort
    daily_bars: DailyBarRepositoryPort
    etf_profiles: EtfProfileRepositoryPort

    def commit(self) -> None:
        """Persist the current transaction to the database."""

    def rollback(self) -> None:
        """Discard every change made in the current transaction."""

    def __enter__(self) -> UnitOfWork:
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        ...


class SqlAlchemyUnitOfWork:
    """SQLAlchemy-backed implementation of :class:`UnitOfWork`.

    A fresh ``Session`` is opened in :meth:`__enter__`; repository
    properties are lazily constructed on first access and reused for the
    rest of the UoW's lifetime. The session is closed in
    :meth:`__exit__` regardless of commit/rollback outcome.
    """

    def __init__(self, session_factory: SessionProvider | sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._instruments: SqlAlchemyInstrumentRepository | None = None
        self._input_snapshot_repository: InputSnapshotRepository | None = None
        self._provider_requests: SqlAlchemyProviderRequestRepository | None = None
        self._provider_attempts: SqlAlchemyProviderAttemptRepository | None = None
        self._provider_batches: SqlAlchemyProviderBatchRepository | None = None
        self._pipeline_runs: SqlAlchemyPipelineRunRepository | None = None
        self._candidate_pool_runs: SqlAlchemyCandidatePoolRunRepository | None = None
        self._candidate_pool_items: SqlAlchemyCandidatePoolItemRepository | None = None
        self._daily_bars: SqlAlchemyDailyBarRepository | None = None
        self._etf_profiles: SqlAlchemyEtfProfileRepository | None = None
        self._closed = True
        self._user_committed = False

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork.session accessed outside of 'with' block; "
                "enter the UnitOfWork context manager first"
            )
        return self._session

    @property
    def instruments(self) -> SqlAlchemyInstrumentRepository:
        if self._instruments is None:
            self._instruments = SqlAlchemyInstrumentRepository(self.session)
        return self._instruments

    @property
    def input_snapshot_repository(self) -> InputSnapshotRepository:
        if self._input_snapshot_repository is None:
            self._input_snapshot_repository = InputSnapshotRepository(self.session)
        return self._input_snapshot_repository

    @property
    def provider_requests(self) -> SqlAlchemyProviderRequestRepository:
        if self._provider_requests is None:
            self._provider_requests = SqlAlchemyProviderRequestRepository(self.session)
        return self._provider_requests

    @property
    def provider_attempts(self) -> SqlAlchemyProviderAttemptRepository:
        if self._provider_attempts is None:
            self._provider_attempts = SqlAlchemyProviderAttemptRepository(self.session)
        return self._provider_attempts

    @property
    def provider_batches(self) -> SqlAlchemyProviderBatchRepository:
        if self._provider_batches is None:
            self._provider_batches = SqlAlchemyProviderBatchRepository(self.session)
        return self._provider_batches

    @property
    def pipeline_runs(self) -> SqlAlchemyPipelineRunRepository:
        if self._pipeline_runs is None:
            self._pipeline_runs = SqlAlchemyPipelineRunRepository(self.session)
        return self._pipeline_runs

    @property
    def candidate_pool_runs(self) -> SqlAlchemyCandidatePoolRunRepository:
        if self._candidate_pool_runs is None:
            self._candidate_pool_runs = SqlAlchemyCandidatePoolRunRepository(self.session)
        return self._candidate_pool_runs

    @property
    def candidate_pool_items(self) -> SqlAlchemyCandidatePoolItemRepository:
        if self._candidate_pool_items is None:
            self._candidate_pool_items = SqlAlchemyCandidatePoolItemRepository(self.session)
        return self._candidate_pool_items

    @property
    def daily_bars(self) -> SqlAlchemyDailyBarRepository:
        if self._daily_bars is None:
            self._daily_bars = SqlAlchemyDailyBarRepository(self.session)
        return self._daily_bars

    @property
    def etf_profiles(self) -> SqlAlchemyEtfProfileRepository:
        if self._etf_profiles is None:
            self._etf_profiles = SqlAlchemyEtfProfileRepository(self.session)
        return self._etf_profiles

    def commit(self) -> None:
        self.session.commit()
        self._user_committed = True

    def rollback(self) -> None:
        self.session.rollback()
        self._user_committed = True

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._closed = False
        self._user_committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                self.rollback()
            elif not self._user_committed:
                try:
                    self.commit()
                except Exception:
                    self.rollback()
                    raise
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None
            self._instruments = None
            self._input_snapshot_repository = None
            self._provider_requests = None
            self._provider_attempts = None
            self._provider_batches = None
            self._pipeline_runs = None
            self._candidate_pool_runs = None
            self._candidate_pool_items = None
            self._daily_bars = None
            self._etf_profiles = None
            self._user_committed = False
            self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


__all__ = [
    "CandidatePoolItemRepositoryPort",
    "CandidatePoolRunRepositoryPort",
    "DailyBarRepositoryPort",
    "EtfProfileRepositoryPort",
    "InputSnapshotRepositoryPort",
    "InstrumentRepositoryPort",
    "PipelineRunRepositoryPort",
    "ProviderAttemptRepositoryPort",
    "ProviderBatchRepositoryPort",
    "ProviderRequestRepositoryPort",
    "SessionProvider",
    "SqlAlchemyUnitOfWork",
    "UnitOfWork",
]