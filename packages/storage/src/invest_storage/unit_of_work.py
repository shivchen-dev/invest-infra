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
  ``uow.candidate_pool_runs``, ``uow.candidate_pool_items``,
  ``uow.research_runs``, ``uow.research_results`` and
  ``uow.strategy_drafts``. The same repository instance is reused for
  the lifetime of the UoW so identity-based caching (e.g. SQLAlchemy's
  identity map) works as expected.
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
    SqlAlchemyEtfHoldingSnapshotRepository,
    SqlAlchemyEtfIndexMappingRepository,
    SqlAlchemyEtfProfileFieldRepository,
    SqlAlchemyEtfProfileRepository,
    SqlAlchemyEvidencePackRepository,
    SqlAlchemyExternalArtifactRepository,
    SqlAlchemyExternalObservationRepository,
    SqlAlchemyExternalWorkflowRunRepository,
    SqlAlchemyIndexConstituentSnapshotRepository,
    SqlAlchemyIndexIdentityRepository,
    SqlAlchemyIndexProfileRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyMarketObservationSnapshotRepository,
    SqlAlchemyPipelineRunRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    SqlAlchemyResearchCaseRepository,
    SqlAlchemyResearchContextPackRepository,
    SqlAlchemyResearchEvidenceBundleRepository,
    SqlAlchemyResearchExternalEvidenceRepository,
    SqlAlchemyResearchResultRepository,
    SqlAlchemyResearchRunRepository,
    SqlAlchemyStockPriceLimitRepository,
    SqlAlchemyStrategyAuditRepository,
    SqlAlchemyStrategyDraftRepository,
    SqlAlchemyStrategyVersionRepository,
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
        market_data_fingerprint: str,
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
class StockPriceLimitRepositoryPort(Protocol):
    """Subset of the StockPriceLimit repository surface the UoW exposes.

    The :class:`invest_storage.repositories.SqlAlchemyStockPriceLimitRepository`
    is the only adapter; the Protocol keeps the application layer
    decoupled from the concrete class. ``upsert_many`` is the only
    write path so callers cannot bypass the row-hash comparison that
    drives the revision allocation. ``get_latest`` and ``get_exact``
    mirror the snapshot-vs-replay split, indexed by
    ``(instrument_id, trade_date)``.
    """

    def upsert_many(self, limits): ...
    def get_latest(self, *, instrument_id, trade_date): ...
    def get_exact(
        self, *, instrument_id, trade_date, revision: int
    ): ...
    def list_by_instrument_and_range(
        self, *, instrument_id, start_date, end_date
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
class EtfProfileFieldRepositoryPort(Protocol):
    """Subset of the EtfProfileField repository surface the UoW exposes.

    ``PR-ETF-PROFILE-04`` introduces
    ``analytics.etf_profile_fields`` and the
    :class:`SqlAlchemyEtfProfileFieldRepository` that wraps it; the
    Protocol mirrors the same public surface so application code can
    type-hint against ``uow.etf_profile_fields`` without importing the
    SQLAlchemy adapter. ``add`` and ``upsert`` are the idempotent write
    paths keyed on ``content_hash``; ``get_by_instrument`` and
    ``get_by_instrument_field`` are the read paths the
    conflict-aware resolver needs.
    """

    def add(self, evidence): ...
    def upsert(self, evidence): ...
    def get_by_instrument(self, instrument_id): ...
    def get_by_instrument_field(self, instrument_id, field_key): ...


@runtime_checkable
class ResearchContextPackRepositoryPort(Protocol):
    def add(self, pack): ...
    def upsert(self, pack): ...
    def get_by_id(self, pack_id): ...
    def get_by_instrument_and_version(self, instrument_id, context_version): ...
    def list_by_instrument(self, instrument_id): ...


@runtime_checkable
class MarketObservationSnapshotRepositoryPort(Protocol):
    """Subset of the MarketObservationSnapshot repository surface the UoW exposes.

    Stage 4B Phase 2 persistence for
    ``analytics.market_observation_snapshots`` /
    ``analytics.market_observations``. ``add`` is idempotent on
    ``content_hash``; snapshots are immutable so there is no update /
    delete surface.
    """

    def add(self, snapshot): ...
    def get_by_id(self, snapshot_row_id): ...
    def get_by_content_hash(self, content_hash): ...
    def list_by_date(self, as_of_date): ...
    def get_latest_for_scope(self, scope_type, scope_key, as_of_date=None): ...


@runtime_checkable
class ExternalWorkflowRunRepositoryPort(Protocol):
    def add(self, run): ...
    def get_by_id(self, run_id): ...
    def list_recent(self, *, limit: int = 50, offset: int = 0): ...


@runtime_checkable
class ExternalArtifactRepositoryPort(Protocol):
    def add(self, artifact): ...
    def get_by_id(self, artifact_id): ...
    def list_by_run(self, run_id, *, limit: int = 100, offset: int = 0): ...


@runtime_checkable
class ExternalObservationRepositoryPort(Protocol):
    def add(self, observation): ...
    def get_by_id(self, observation_id): ...
    def list_by_run(self, run_id, *, limit: int = 100, offset: int = 0): ...
    def list_by_admission_status(self, status, *, limit: int = 100, offset: int = 0): ...
    def list_recent(self, *, status=None, limit: int = 100, offset: int = 0): ...
    def save_admission(self, observation): ...
    def save_resolution(self, observation): ...


@runtime_checkable
class ResearchExternalEvidenceRepositoryPort(Protocol):
    def add(self, research_case_id, item): ...
    def list_by_case(self, research_case_id): ...
    def get_by_observation(self, observation_id): ...


@runtime_checkable
class ResearchCaseRepositoryPort(Protocol):
    """Subset of the ResearchCase repository surface the UoW exposes."""

    def add(self, case): ...
    def get(self, case_id): ...
    def list_by_instrument(self, instrument_id): ...
    def save_transition(self, previous_status, transitioned_case): ...
    def list_recent(self, *, limit: int = 50, offset: int = 0): ...
    def count_all(self) -> int: ...


@runtime_checkable
class ResearchEvidencePackRepositoryPort(Protocol):
    """Subset of the ResearchEvidencePack repository surface the UoW exposes.

    Phase 2B persistence closure for ``analytics.research_evidence_packs``
    (migration ``20260807_0013``). ``add`` is idempotent on
    ``content_hash``; the read paths expose deterministic ordering
    (``created_at`` / ``id`` for ``list_by_case``;
    ``as_of_date`` / ``created_at`` / ``id`` for ``list_by_instrument``).
    There is no update / delete surface because packs are immutable.
    """

    def add(self, pack): ...
    def get_by_id(self, pack_id): ...
    def get_by_content_hash(self, content_hash): ...
    def list_by_case(self, case_id): ...
    def list_by_instrument(self, instrument_id, as_of_date=None): ...


@runtime_checkable
class ResearchEvidenceBundleRepositoryPort(Protocol):
    """Subset of the ResearchEvidenceBundle repository surface the UoW exposes.

    Stage 4B Phase 3 persistence closure for
    ``analytics.research_evidence_bundles`` (migration
    ``20260811_0016``). ``add`` is idempotent on ``bundle_hash``;
    bundles are immutable so there is no update / delete surface.
    Per plan, a changed market snapshot set for the same
    ``(research_case_id, evidence_pack_id)`` pair MUST create a new
    bundle identity, so the table has no ``(research_case_id,
    evidence_pack_id)`` unique constraint — the application layer
    relies on ``get_by_case_and_pack`` (newest first, ``bundle_id``
    tie-break) for a deterministic "current" bundle.
    ``get_by_id`` / ``get_by_bundle_hash`` /
    ``get_by_case_and_pack`` / ``list_by_case`` mirror the
    deterministic ordering expected by the application layer.
    """

    def add(self, bundle): ...
    def get_by_id(self, bundle_id): ...
    def get_by_bundle_hash(self, bundle_hash): ...
    def get_by_case_and_pack(self, *, research_case_id, evidence_pack_id): ...
    def list_by_case(self, research_case_id): ...


@runtime_checkable
class ResearchRunRepositoryPort(Protocol):
    """Subset of the ResearchRun repository surface the UoW exposes.

    PR-5.5 lifecycle owner for ``analytics.research_runs``; the
    Protocol mirrors the SQLAlchemy adapter's public surface so the
    application layer can type-hint against ``uow.research_runs``
    without importing the concrete class.
    :meth:`save_transition` is the CAS-aware UPDATE path; the
    bind/lookup helpers are reserved for the later JiuwenSwarm adapter.
    """

    def add(self, run): ...
    def get(self, run_id): ...
    def list_by_case(self, case_id): ...
    def save_transition(self, previous_status, transitioned_run): ...
    def bind_external_identity(
        self,
        run_id,
        *,
        external_request_id=None,
        external_session_id=None,
    ): ...
    def lookup_by_external_session_id(self, external_session_id): ...
    def list_recent(self, *, limit: int = 50, offset: int = 0): ...
    def count_all(self) -> int: ...


@runtime_checkable
class ResearchResultRepositoryPort(Protocol):
    """Subset of the ResearchResult repository surface the UoW exposes.

    PR-5.5 closure for the immutable ``analytics.research_results``
    rows. The Protocol mirrors the SQLAlchemy adapter's public surface
    so the application layer can type-hint against
    ``uow.research_results`` without importing the concrete class.
    ``add`` is idempotent on the natural unique constraint on
    ``run_id`` and raises :class:`ResearchResultConflictError` when the
    incoming payload diverges from the stored row; the read paths are
    simple round-trips on the primary key and the natural key.
    """

    def add(self, result): ...
    def get_by_id(self, result_id): ...
    def get_by_run_id(self, run_id): ...


@runtime_checkable
class IndexIdentityRepositoryPort(Protocol):
    """Subset of the IndexIdentity repository surface the UoW exposes.

    Stage DC-3 introduces ``core.indexes`` and the
    :class:`SqlAlchemyIndexIdentityRepository` that wraps it; the
    Protocol mirrors the same public surface so application code can
    type-hint against ``uow.index_identities`` without importing the
    SQLAlchemy adapter.
    """

    def add(self, *, index_code: str, index_name: str, category: str | None = None): ...
    def get_by_id(self, identity_id): ...
    def get_by_index_code(self, index_code: str): ...
    def list_by_index_code(self, index_code: str, *, limit: int = 100, offset: int = 0): ...


@runtime_checkable
class IndexProfileRepositoryPort(Protocol):
    """Subset of the IndexProfile repository surface the UoW exposes.

    Stage DC-3 introduces ``core.index_profiles`` and the
    :class:`SqlAlchemyIndexProfileRepository` that wraps it; the
    Protocol mirrors the same public surface so application code can
    type-hint against ``uow.index_profiles`` without importing the
    SQLAlchemy adapter. ``add`` and ``upsert`` are the idempotent
    write paths keyed on ``content_hash``; ``get_by_id``,
    ``find_by_content_hash``, ``list_by_index_id`` and
    ``list_by_provider`` are the read paths the Stage DC-3
    applications need.
    """

    def add(self, profile, index_id): ...
    def upsert(self, profile, index_id): ...
    def get_by_id(self, profile_id): ...
    def find_by_content_hash(self, content_hash): ...
    def list_by_index_id(self, index_id, *, limit: int = 100, offset: int = 0): ...
    def list_by_provider(
        self, provider_key, *, limit: int = 100, offset: int = 0
    ): ...


@runtime_checkable
class IndexConstituentSnapshotRepositoryPort(Protocol):
    """Subset of the IndexConstituentSnapshot repository surface.

    Children rows are written in the same transaction as the parent
    snapshot and re-read on every domain-side round-trip so the
    callers receive a fully-populated
    :class:`invest_domain.exposure.models.IndexConstituentSnapshot`.
    """

    def add(self, snapshot, index_id): ...
    def get_by_id(self, snapshot_id): ...
    def find_by_content_hash(self, content_hash): ...
    def list_by_index_id(
        self, index_id, *, limit: int = 100, offset: int = 0
    ): ...


@runtime_checkable
class EtfIndexMappingRepositoryPort(Protocol):
    """Subset of the EtfIndexMapping repository surface.

    The natural idempotency key is ``content_hash``; the repository
    never rewrites a row that already carries the same business
    content so a re-collect of the same observation returns the
    pre-existing ``StoredEtfIndexMapping.id``.
    """

    def add(self, mapping): ...
    def upsert(self, mapping): ...
    def get_by_id(self, mapping_id): ...
    def list_by_etf_id(self, etf_id, *, limit: int = 100, offset: int = 0): ...
    def list_by_index_id(self, index_id, *, limit: int = 100, offset: int = 0): ...


@runtime_checkable
class EtfHoldingSnapshotRepositoryPort(Protocol):
    """Subset of the EtfHoldingSnapshot repository surface.

    Mirrors the snapshot pattern of
    :class:`IndexConstituentSnapshotRepositoryPort`: the parent row
    carries the natural idempotency key on ``content_hash`` and the
    child ``etf_holdings`` rows FK back with ``ON DELETE CASCADE``.
    """

    def add(self, snapshot): ...
    def get_by_id(self, snapshot_id): ...
    def find_by_content_hash(self, content_hash): ...
    def list_by_etf_id(self, etf_id, *, limit: int = 100, offset: int = 0): ...


@runtime_checkable
class StrategyDraftRepositoryPort(Protocol):
    """Subset of the StrategyDraft repository surface the UoW exposes.

    The :class:`invest_storage.repositories.SqlAlchemyStrategyDraftRepository`
    is the only adapter; the Protocol keeps the application layer
    decoupled from the concrete class.
    """

    def add(self, draft): ...
    def get_by_id(self, draft_id): ...
    def get_by_artifact_hash(self, artifact_hash): ...
    def get_by_strategy_key_proposed_version(
        self, strategy_key, proposed_version
    ): ...


@runtime_checkable
class StrategyAuditRepositoryPort(Protocol):
    def add(self, audit): ...
    def get_by_id(self, audit_id): ...
    def list_by_draft(self, draft_id): ...


@runtime_checkable
class StrategyVersionRepositoryPort(Protocol):
    """Subset of the StrategyVersion repository surface the UoW exposes.

    The :class:`invest_storage.repositories.SqlAlchemyStrategyVersionRepository`
    is the only adapter; the Protocol keeps the application layer
    decoupled from the concrete class.
    """

    def add(self, version): ...
    def get_by_id(self, strategy_id): ...
    def get_active(self, strategy_key): ...
    def activate(self, strategy_id, *, at): ...


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
    stock_price_limits: StockPriceLimitRepositoryPort
    etf_profiles: EtfProfileRepositoryPort
    etf_profile_fields: EtfProfileFieldRepositoryPort
    research_context_packs: ResearchContextPackRepositoryPort
    market_observation_snapshots: MarketObservationSnapshotRepositoryPort
    research_cases: ResearchCaseRepositoryPort
    research_evidence_packs: ResearchEvidencePackRepositoryPort
    research_evidence_bundles: ResearchEvidenceBundleRepositoryPort
    research_runs: ResearchRunRepositoryPort
    research_results: ResearchResultRepositoryPort
    index_identities: IndexIdentityRepositoryPort
    index_profiles: IndexProfileRepositoryPort
    index_constituent_snapshots: IndexConstituentSnapshotRepositoryPort
    etf_index_mappings: EtfIndexMappingRepositoryPort
    etf_holding_snapshots: EtfHoldingSnapshotRepositoryPort
    external_workflow_runs: ExternalWorkflowRunRepositoryPort
    external_artifacts: ExternalArtifactRepositoryPort
    external_observations: ExternalObservationRepositoryPort
    research_external_evidence: ResearchExternalEvidenceRepositoryPort
    strategy_drafts: StrategyDraftRepositoryPort
    strategy_audits: StrategyAuditRepositoryPort
    strategy_versions: StrategyVersionRepositoryPort

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
        self._stock_price_limits: SqlAlchemyStockPriceLimitRepository | None = None
        self._etf_profiles: SqlAlchemyEtfProfileRepository | None = None
        self._etf_profile_fields: SqlAlchemyEtfProfileFieldRepository | None = None
        self._research_context_packs: SqlAlchemyResearchContextPackRepository | None = None
        self._market_observation_snapshots: SqlAlchemyMarketObservationSnapshotRepository | None = (
            None
        )
        self._research_cases: SqlAlchemyResearchCaseRepository | None = None
        self._research_evidence_packs: SqlAlchemyEvidencePackRepository | None = None
        self._research_evidence_bundles: (
            SqlAlchemyResearchEvidenceBundleRepository | None
        ) = None
        self._research_runs: SqlAlchemyResearchRunRepository | None = None
        self._research_results: SqlAlchemyResearchResultRepository | None = None
        self._index_identities: SqlAlchemyIndexIdentityRepository | None = None
        self._index_profiles: SqlAlchemyIndexProfileRepository | None = None
        self._index_constituent_snapshots: SqlAlchemyIndexConstituentSnapshotRepository | None = (
            None
        )
        self._etf_index_mappings: SqlAlchemyEtfIndexMappingRepository | None = None
        self._etf_holding_snapshots: SqlAlchemyEtfHoldingSnapshotRepository | None = (
            None
        )
        self._external_workflow_runs: SqlAlchemyExternalWorkflowRunRepository | None = None
        self._external_artifacts: SqlAlchemyExternalArtifactRepository | None = None
        self._external_observations: SqlAlchemyExternalObservationRepository | None = None
        self._research_external_evidence: SqlAlchemyResearchExternalEvidenceRepository | None = None
        self._strategy_drafts: SqlAlchemyStrategyDraftRepository | None = None
        self._strategy_audits: SqlAlchemyStrategyAuditRepository | None = None
        self._strategy_versions: SqlAlchemyStrategyVersionRepository | None = None
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
    def stock_price_limits(self) -> SqlAlchemyStockPriceLimitRepository:
        if self._stock_price_limits is None:
            self._stock_price_limits = SqlAlchemyStockPriceLimitRepository(self.session)
        return self._stock_price_limits

    @property
    def etf_profiles(self) -> SqlAlchemyEtfProfileRepository:
        if self._etf_profiles is None:
            self._etf_profiles = SqlAlchemyEtfProfileRepository(self.session)
        return self._etf_profiles

    @property
    def etf_profile_fields(self) -> SqlAlchemyEtfProfileFieldRepository:
        if self._etf_profile_fields is None:
            self._etf_profile_fields = SqlAlchemyEtfProfileFieldRepository(
                self.session
            )
        return self._etf_profile_fields

    @property
    def research_context_packs(self) -> SqlAlchemyResearchContextPackRepository:
        if self._research_context_packs is None:
            self._research_context_packs = SqlAlchemyResearchContextPackRepository(
                self.session
            )
        return self._research_context_packs

    @property
    def market_observation_snapshots(self) -> SqlAlchemyMarketObservationSnapshotRepository:
        if self._market_observation_snapshots is None:
            self._market_observation_snapshots = SqlAlchemyMarketObservationSnapshotRepository(
                self.session
            )
        return self._market_observation_snapshots

    @property
    def research_cases(self) -> SqlAlchemyResearchCaseRepository:
        if self._research_cases is None:
            self._research_cases = SqlAlchemyResearchCaseRepository(self.session)
        return self._research_cases

    @property
    def research_evidence_packs(self) -> SqlAlchemyEvidencePackRepository:
        if self._research_evidence_packs is None:
            self._research_evidence_packs = SqlAlchemyEvidencePackRepository(
                self.session
            )
        return self._research_evidence_packs

    @property
    def research_evidence_bundles(
        self,
    ) -> SqlAlchemyResearchEvidenceBundleRepository:
        if self._research_evidence_bundles is None:
            self._research_evidence_bundles = (
                SqlAlchemyResearchEvidenceBundleRepository(self.session)
            )
        return self._research_evidence_bundles

    @property
    def research_runs(self) -> SqlAlchemyResearchRunRepository:
        if self._research_runs is None:
            self._research_runs = SqlAlchemyResearchRunRepository(self.session)
        return self._research_runs

    @property
    def research_results(self) -> SqlAlchemyResearchResultRepository:
        if self._research_results is None:
            self._research_results = SqlAlchemyResearchResultRepository(self.session)
        return self._research_results

    @property
    def index_identities(self) -> SqlAlchemyIndexIdentityRepository:
        if self._index_identities is None:
            self._index_identities = SqlAlchemyIndexIdentityRepository(self.session)
        return self._index_identities

    @property
    def index_profiles(self) -> SqlAlchemyIndexProfileRepository:
        if self._index_profiles is None:
            self._index_profiles = SqlAlchemyIndexProfileRepository(self.session)
        return self._index_profiles

    @property
    def index_constituent_snapshots(self) -> SqlAlchemyIndexConstituentSnapshotRepository:
        if self._index_constituent_snapshots is None:
            self._index_constituent_snapshots = SqlAlchemyIndexConstituentSnapshotRepository(
                self.session
            )
        return self._index_constituent_snapshots

    @property
    def etf_index_mappings(self) -> SqlAlchemyEtfIndexMappingRepository:
        if self._etf_index_mappings is None:
            self._etf_index_mappings = SqlAlchemyEtfIndexMappingRepository(self.session)
        return self._etf_index_mappings

    @property
    def etf_holding_snapshots(self) -> SqlAlchemyEtfHoldingSnapshotRepository:
        if self._etf_holding_snapshots is None:
            self._etf_holding_snapshots = SqlAlchemyEtfHoldingSnapshotRepository(
                self.session
            )
        return self._etf_holding_snapshots

    @property
    def external_workflow_runs(self) -> SqlAlchemyExternalWorkflowRunRepository:
        if self._external_workflow_runs is None:
            self._external_workflow_runs = SqlAlchemyExternalWorkflowRunRepository(self.session)
        return self._external_workflow_runs

    @property
    def external_artifacts(self) -> SqlAlchemyExternalArtifactRepository:
        if self._external_artifacts is None:
            self._external_artifacts = SqlAlchemyExternalArtifactRepository(self.session)
        return self._external_artifacts

    @property
    def external_observations(self) -> SqlAlchemyExternalObservationRepository:
        if self._external_observations is None:
            self._external_observations = SqlAlchemyExternalObservationRepository(self.session)
        return self._external_observations

    @property
    def research_external_evidence(self) -> SqlAlchemyResearchExternalEvidenceRepository:
        if self._research_external_evidence is None:
            self._research_external_evidence = SqlAlchemyResearchExternalEvidenceRepository(
                self.session
            )
        return self._research_external_evidence

    @property
    def strategy_drafts(self) -> SqlAlchemyStrategyDraftRepository:
        if self._strategy_drafts is None:
            self._strategy_drafts = SqlAlchemyStrategyDraftRepository(self.session)
        return self._strategy_drafts

    @property
    def strategy_audits(self) -> SqlAlchemyStrategyAuditRepository:
        if self._strategy_audits is None:
            self._strategy_audits = SqlAlchemyStrategyAuditRepository(self.session)
        return self._strategy_audits

    @property
    def strategy_versions(self) -> SqlAlchemyStrategyVersionRepository:
        if self._strategy_versions is None:
            self._strategy_versions = SqlAlchemyStrategyVersionRepository(self.session)
        return self._strategy_versions

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
            self._stock_price_limits = None
            self._etf_profiles = None
            self._etf_profile_fields = None
            self._research_context_packs = None
            self._market_observation_snapshots = None
            self._research_cases = None
            self._research_evidence_packs = None
            self._research_evidence_bundles = None
            self._research_runs = None
            self._research_results = None
            self._index_identities = None
            self._index_profiles = None
            self._index_constituent_snapshots = None
            self._etf_index_mappings = None
            self._etf_holding_snapshots = None
            self._external_workflow_runs = None
            self._external_artifacts = None
            self._external_observations = None
            self._research_external_evidence = None
            self._strategy_drafts = None
            self._strategy_audits = None
            self._strategy_versions = None
            self._user_committed = False
            self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


__all__ = [
    "CandidatePoolItemRepositoryPort",
    "CandidatePoolRunRepositoryPort",
    "DailyBarRepositoryPort",
    "EtfHoldingSnapshotRepositoryPort",
    "ExternalArtifactRepositoryPort",
    "ExternalObservationRepositoryPort",
    "ExternalWorkflowRunRepositoryPort",
    "EtfIndexMappingRepositoryPort",
    "EtfProfileFieldRepositoryPort",
    "EtfProfileRepositoryPort",
    "IndexConstituentSnapshotRepositoryPort",
    "IndexIdentityRepositoryPort",
    "IndexProfileRepositoryPort",
    "ResearchCaseRepositoryPort",
    "ResearchContextPackRepositoryPort",
    "ResearchEvidenceBundleRepositoryPort",
    "ResearchEvidencePackRepositoryPort",
    "ResearchResultRepositoryPort",
    "ResearchRunRepositoryPort",
    "EtfProfileRepositoryPort",
    "InputSnapshotRepositoryPort",
    "InstrumentRepositoryPort",
    "MarketObservationSnapshotRepositoryPort",
    "PipelineRunRepositoryPort",
    "ProviderAttemptRepositoryPort",
    "ProviderBatchRepositoryPort",
    "ProviderRequestRepositoryPort",
    "SessionProvider",
    "StockPriceLimitRepositoryPort",
    "StrategyDraftRepositoryPort",
    "StrategyAuditRepositoryPort",
    "StrategyVersionRepositoryPort",
    "SqlAlchemyUnitOfWork",
    "UnitOfWork",
]  # noqa: E501
