"""Shared fixtures for the apps/api tests.

The tests are mock-based: each test patches the storage-layer repository
classes used by the routers so the endpoints can be exercised without a
live PostgreSQL connection. A ``mock_session`` fixture overrides the
``get_db_session`` FastAPI dependency so the routers always receive a
``MagicMock`` ``Session`` instance; the per-test ``monkeypatch`` calls
then attach controlled return values to the repository mocks.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.dependencies import get_db_session, get_pipeline_run_query_service
from invest_api.main import app
from invest_api.routers import candidate_pool as candidate_pool_router
from invest_api.routers import etf as etf_router
from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
    ExclusionReason,
    RuleOutcome,
    RuleSeverity,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_domain.shared.values import Currency
from invest_storage.repositories import StoredDailyBar


@pytest.fixture()
def mock_session() -> MagicMock:
    """Return a ``MagicMock`` that quacks like a SQLAlchemy ``Session``."""

    return MagicMock(name="Session")


@pytest.fixture()
def client(mock_session: MagicMock) -> TestClient:
    """Return a ``TestClient`` with ``get_db_session`` overridden to a mock session."""

    app.dependency_overrides[get_db_session] = lambda: mock_session
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture()
def instrument_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``SqlAlchemyInstrumentRepository`` in the ETF router with a mock."""

    mock = MagicMock(name="InstrumentRepository")
    monkeypatch.setattr(
        etf_router, "SqlAlchemyInstrumentRepository", lambda session: mock
    )
    return mock


@pytest.fixture()
def daily_bar_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``SqlAlchemyDailyBarRepository`` in the ETF router with a mock."""

    mock = MagicMock(name="DailyBarRepository")
    monkeypatch.setattr(
        etf_router, "SqlAlchemyDailyBarRepository", lambda session: mock
    )
    return mock


@pytest.fixture()
def candidate_pool_run_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``SqlAlchemyCandidatePoolRunRepository`` in the candidate-pool router."""

    mock = MagicMock(name="CandidatePoolRunRepository")
    monkeypatch.setattr(
        candidate_pool_router,
        "SqlAlchemyCandidatePoolRunRepository",
        lambda session: mock,
    )
    return mock


@pytest.fixture()
def candidate_pool_item_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``SqlAlchemyCandidatePoolItemRepository`` in the candidate-pool router."""

    mock = MagicMock(name="CandidatePoolItemRepository")
    monkeypatch.setattr(
        candidate_pool_router,
        "SqlAlchemyCandidatePoolItemRepository",
        lambda session: mock,
    )
    return mock


@pytest.fixture()
def input_snapshot_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``InputSnapshotRepository`` in the candidate-pool router."""

    mock = MagicMock(name="InputSnapshotRepository")
    monkeypatch.setattr(
        candidate_pool_router, "InputSnapshotRepository", lambda session: mock
    )
    return mock


@pytest.fixture()
def candidate_pool_instrument_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``SqlAlchemyInstrumentRepository`` in the candidate-pool router."""

    mock = MagicMock(name="CandidatePoolInstrumentRepository")
    mock.get_many_by_ids.return_value = {}
    monkeypatch.setattr(
        candidate_pool_router,
        "SqlAlchemyInstrumentRepository",
        lambda session: mock,
    )
    return mock


@pytest.fixture()
def pipeline_run_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a mock :class:`PipelineRunQueryService` into the pipeline-runs router.

    Overrides :func:`invest_api.dependencies.get_pipeline_run_query_service`
    so the router receives a ``MagicMock`` that quacks like the
    application service. Endpoint tests configure return values and
    side effects on this mock; the service-level tests bypass the
    HTTP layer and construct the real service against a mock
    repository instead.
    """

    mock = MagicMock(name="PipelineRunQueryService")
    app.dependency_overrides[get_pipeline_run_query_service] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_pipeline_run_query_service, None)


def make_instrument(
    *,
    symbol: str = "510050",
    name: str = "SSE 50 ETF",
    exchange: str = "SSE",
    instrument_type: InstrumentType = InstrumentType.ETF,
    is_active: bool = True,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
    instrument_id: InstrumentId | None = None,
    category: str | None = None,
    underlying_index: str | None = None,
    list_date: date | None = date(2020, 1, 1),
    delist_date: date | None = None,
) -> Instrument:
    """Build a minimal valid :class:`Instrument` for endpoint input."""

    if status is InstrumentStatus.DELISTED and delist_date is None:
        delist_date = date(2026, 1, 1)
    return Instrument(
        symbol=symbol,
        name=name,
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        status=status,
        instrument_id=instrument_id,
        currency=Currency.CNY,
        category=category,
        underlying_index=underlying_index,
        list_date=list_date,
        delist_date=delist_date,
    )


def make_daily_bar(
    *,
    instrument_id: UUID,
    trade_date: date,
    open: Decimal = Decimal("1.000"),
    high: Decimal = Decimal("1.020"),
    low: Decimal = Decimal("0.990"),
    close: Decimal = Decimal("1.010"),
    prev_close: Decimal = Decimal("1.000"),
    volume: Decimal = Decimal("1000"),
    amount: Decimal = Decimal("1010"),
    adjustment: str = "none",
    trading_status: str = "normal",
    source_provider: str = "fixture_dev",
    revision: int = 1,
    row_hash: str | None = None,
) -> StoredDailyBar:
    """Build a :class:`StoredDailyBar` shaped for the API response."""

    return StoredDailyBar(
        id=uuid4(),
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=open,
        high=high,
        low=low,
        close=close,
        prev_close=prev_close,
        volume=volume,
        amount=amount,
        adjustment=adjustment,
        trading_status=trading_status,
        source_provider=source_provider,
        source_batch_id=uuid4(),
        observed_at=datetime(2026, 7, 31, 9, tzinfo=UTC),
        revision=revision,
        row_hash=row_hash or ("a" * 64),
    )


def make_input_snapshot(
    *,
    snapshot_date: date,
    instrument_ids: list[UUID] | None = None,
    row_count: int | None = None,
    content_hash: str = "f" * 64,
) -> InputSnapshot:
    """Build a deterministic :class:`InputSnapshot` for the candidate-pool response."""

    ids = tuple(instrument_ids or [uuid4(), uuid4()])
    return InputSnapshot(
        id=uuid4(),
        snapshot_date=snapshot_date,
        instrument_ids=ids,
        content_hash=content_hash,
        row_count=row_count if row_count is not None else len(ids),
        created_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
    )


def make_candidate_pool_run(
    *,
    trade_date: date = date(2026, 7, 31),
    status: CandidatePoolStatus = CandidatePoolStatus.PUBLISHED,
    input_snapshot_id: UUID | None = None,
    input_row_count: int = 3,
    included_count: int | None = None,
    rejection_reason: str | None = None,
) -> CandidatePoolRun:
    """Build a :class:`CandidatePoolRun` for the ``latest`` endpoint."""

    effective_included = input_row_count if included_count is None else included_count
    published_at = (
        datetime(2026, 7, 31, 10, tzinfo=UTC) if status is CandidatePoolStatus.PUBLISHED else None
    )
    rejected_at = (
        datetime(2026, 7, 31, 10, tzinfo=UTC) if status is CandidatePoolStatus.REJECTED else None
    )
    effective_rejection_reason = (
        rejection_reason
        if rejection_reason is not None
        else (
            "rejected during validation"
            if status is CandidatePoolStatus.REJECTED
            else None
        )
    )
    return CandidatePoolRun(
        id=uuid4(),
        trade_date=trade_date,
        algorithm_key="candidate_pool.v1",
        algorithm_version="v1.0",
        parameter_set_key="default",
        parameter_hash="a" * 64,
        input_snapshot_id=input_snapshot_id or uuid4(),
        input_row_count=input_row_count,
        included_count=effective_included,
        status=status,
        created_at=datetime(2026, 7, 31, 9, tzinfo=UTC),
        published_at=published_at,
        rejected_at=rejected_at,
        rejection_reason=effective_rejection_reason,
    )


def make_pool_item(
    *,
    instrument_id: UUID,
    included: bool = True,
    rank: int | None = 1,
    total_score: Decimal | None = Decimal("0.85"),
) -> CandidatePoolItem:
    """Build a :class:`CandidatePoolItem` for the ``latest`` endpoint."""

    if included:
        return CandidatePoolItem(
            instrument_id=InstrumentId(instrument_id),
            included=True,
            rank=rank,
            total_score=total_score,
            metrics={"liquidity": Decimal("1.5")},
            rule_results=(
                RuleOutcome(
                    rule_key="liquidity",
                    passed=True,
                    severity=RuleSeverity.INFO,
                    value=Decimal("1.5"),
                    threshold=Decimal("1.0"),
                ),
            ),
        )
    return CandidatePoolItem(
        instrument_id=InstrumentId(instrument_id),
        included=False,
        rank=None,
        total_score=None,
        metrics={},
        exclusion_reasons=(
            ExclusionReason(code="suspended", message="trading suspended"),
        ),
    )


def make_pipeline_run(
    *,
    job_key: str = "personal_etf_daily_job",
    trigger_type: str = "scheduled",
    status: PipelineRunStatus = PipelineRunStatus.SUCCEEDED,
    partition_key: str | None = "2026-07-31",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_summary: str | None = None,
    run_id: UUID | None = None,
) -> PipelineRun:
    """Build a :class:`PipelineRun` for the ``pipeline-runs`` endpoints."""

    started = started_at
    if started is None and status is not PipelineRunStatus.QUEUED:
        started = datetime(2026, 7, 31, 9, tzinfo=UTC)
    finished = finished_at
    if finished is None and status in (
        PipelineRunStatus.SUCCEEDED,
        PipelineRunStatus.FAILED,
        PipelineRunStatus.PARTIAL,
        PipelineRunStatus.CANCELLED,
    ):
        finished = datetime(2026, 7, 31, 10, tzinfo=UTC)
    if status is PipelineRunStatus.FAILED and error_summary is None:
        error_summary = "personal daily job failed in fixtures"
    return PipelineRun(
        id=run_id or uuid4(),
        dagster_run_id=None,
        job_key=job_key,
        partition_key=partition_key,
        trigger_type=trigger_type,
        algorithm_version="v1.0",
        config_snapshot={},
        status=status,
        started_at=started,
        finished_at=finished,
        error_summary=error_summary,
    )


__all__ = [
    "candidate_pool_instrument_repo",
    "candidate_pool_item_repo",
    "candidate_pool_run_repo",
    "client",
    "daily_bar_repo",
    "input_snapshot_repo",
    "instrument_repo",
    "make_candidate_pool_run",
    "make_daily_bar",
    "make_input_snapshot",
    "make_instrument",
    "make_pipeline_run",
    "make_pool_item",
    "mock_session",
    "pipeline_run_service",
]