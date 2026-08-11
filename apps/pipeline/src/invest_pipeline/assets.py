from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import dagster as dg
from invest_domain.instruments import Instrument
from invest_storage.database import build_engine, session_factory
from invest_storage.models import InstrumentRow
from invest_storage.repositories import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    _row_to_instrument,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from invest_pipeline.adapters import FixtureDevInstrumentProvider
from invest_pipeline.candidate_pool_service import (
    CandidatePoolSnapshotNotFoundError,
    calculate_and_publish_candidate_pool,
    load_candidate_pool_policy,
)
from invest_pipeline.config import get_settings
from invest_pipeline.etf_daily_bars import (
    upsert_etf_daily_bars,
    write_etf_daily_bars_raw,
)
from invest_pipeline.etf_instruments import (
    upsert_etf_instruments,
    write_etf_instruments_raw,
)
from invest_pipeline.input_snapshot import create_input_snapshot
from invest_pipeline.market_breadth_service import (
    MarketBreadthInsufficientDataError,
    calculate_and_publish_market_breadth,
    list_active_stock_instrument_ids,
)
from invest_pipeline.personal_universe import (
    load_personal_universe,
    resolve_personal_universe,
)
from invest_pipeline.provider_factory import build_provider, build_stock_provider
from invest_pipeline.request_keys import make_daily_bars_request_key
from invest_pipeline.stock_daily_bars import (
    upsert_stock_daily_bars,
)
from invest_pipeline.stock_universe import load_stock_universe  # noqa: F401

# ``load_stock_universe`` is preserved as a module-level attribute so
# the by-date raw-asset wiring tests can ``patch.object(assets,
# "load_stock_universe", ...)`` without ``create=True``; no asset
# calls it after the Stage 4B dynamic-universe slice.

_ETF_INPUT_SNAPSHOT_PARTITIONS = dg.DailyPartitionsDefinition(start_date="2026-07-23")


_STOCK_MARKET_DATA_PARTITIONS = dg.DailyPartitionsDefinition(start_date="2026-07-23")


@dg.asset(group_name="market_data", compute_kind="python")
def seed_instruments(context) -> dg.MaterializeResult:
    """Seed the canonical ``core.instruments`` rows from the fixture_dev adapter.

    PR-02: the adapter returns the three-layer evidence bundle
    ``(ProviderRequest, ProviderAttempt, ProviderBatch)``. The asset
    persists each layer via its repository in order (request → attempt
    → batch), so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The standardized records (``batch.records``) are then upserted into
    ``core.instruments`` via :class:`SqlAlchemyInstrumentRepository`.
    """

    provider = FixtureDevInstrumentProvider()
    request, attempt, batch = provider.fetch_instruments(date.today())

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    session: Session = factory()
    try:
        request_repo = SqlAlchemyProviderRequestRepository(session)
        attempt_repo = SqlAlchemyProviderAttemptRepository(session)
        batch_repo = SqlAlchemyProviderBatchRepository(session)
        instrument_repo = SqlAlchemyInstrumentRepository(session)

        stored_request = request_repo.add(
            NewProviderRequest(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                status="pending",
                request_params=dict(request.params),
            )
        )

        stored_attempt = attempt_repo.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=attempt.attempt_number,
                started_at=attempt.started_at,
                status="succeeded",
                finished_at=attempt.finished_at,
            )
        )

        if batch is not None:
            batch_repo.add(
                NewProviderBatch(
                    provider_request_id=stored_request.id,
                    provider_attempt_id=stored_attempt.id,
                    provider_key=request.provider_key,
                    dataset_key=request.dataset_key,
                    record_count=len(batch.records),
                    payload_sha256=batch.raw_payload_hash,
                    status=batch.status.value,
                    warnings=list(batch.warnings),
                )
            )

        count = instrument_repo.upsert_many(batch.records if batch else ())
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

    context.log.info(
        "Upserted %s instruments via provider=%s request=%s attempt=%s",
        count,
        request.provider_key,
        stored_request.id,
        stored_attempt.id,
    )
    return dg.MaterializeResult(
        metadata={
            "row_count": count,
            "provider": request.provider_key,
            "request_id": str(stored_request.id),
            "attempt_id": str(stored_attempt.id),
        }
    )


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    partitions_def=_ETF_INPUT_SNAPSHOT_PARTITIONS,
)
def etf_instruments_raw(context) -> dg.MaterializeResult:
    """Persist the PR-02 three-layer evidence bundle for ETF master data.

    Calls the ``fixture_dev`` adapter, hands the request / attempt /
    batch triple to :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`,
    and surfaces the storage-assigned UUIDs through Dagster metadata.

    The business date comes from ``context.partition_key`` only (no
    ``date.today()`` fallback) so a back-fill run for a historical
    partition cannot silently re-target today's data. The partition
    definition is shared with :func:`etf_daily_bars_raw`,
    :func:`etf_daily_bars`, :func:`etf_input_snapshot` and
    :func:`personal_candidate_pool` so all five daily assets consume
    the same trade date for any given partition.

    A failed attempt persists the request + attempt only — no batch row
    is created. The downstream :func:`etf_instruments` asset inspects
    the persisted state to decide whether to upsert standardized
    records or skip with a note.
    """

    as_of = date.fromisoformat(context.partition_key)
    provider = build_provider(get_settings())
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        result = write_etf_instruments_raw(
            provider,
            factory,
            as_of=as_of,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_instruments_raw: provider=%s request=%s attempt=%s batch=%s "
        "status=%s records=%s as_of=%s",
        provider.provider_key,
        result.request_id,
        result.attempt_id,
        result.batch_id,
        result.request_status,
        result.record_count,
        as_of.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "provider": provider.provider_key,
            "request_id": str(result.request_id),
            "attempt_id": str(result.attempt_id),
            "batch_id": str(result.batch_id) if result.batch_id else "",
            "request_status": result.request_status,
            "attempt_status": result.attempt_status,
            "record_count": result.record_count,
            "as_of": as_of.isoformat(),
            "partition_key": context.partition_key,
        }
    )


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    deps=[etf_instruments_raw],
    partitions_def=_ETF_INPUT_SNAPSHOT_PARTITIONS,
)
def etf_instruments(context) -> dg.MaterializeResult:
    """Upsert standardized ETF instruments into ``core.instruments``.

    Depends on :func:`etf_instruments_raw` and re-opens a fresh
    transaction to read the persisted attempt's
    ``response_payload_json`` sidecar. The records are deserialized
    back into domain :class:`Instrument` instances and upserted via
    :class:`SqlAlchemyInstrumentRepository`. The upsert is idempotent
    on the partial unique business key
    ``(symbol, exchange) WHERE delist_date IS NULL``.

    The business date comes from ``context.partition_key`` only (no
    ``date.today()`` fallback) so a back-fill run for a historical
    partition cannot silently re-target today's data. The partition
    definition is shared with :func:`etf_instruments_raw` and the rest
    of the daily slice so the upstream request lookup
    ``(provider_key, dataset_key, request_key=instruments-{as_of})``
    always resolves the attempt the partitioned raw write just
    persisted.

    If the upstream attempt failed the asset surfaces a
    :class:`MaterializeResult` with ``row_count=0`` and a
    ``skipped`` note rather than raising, so a contract-test failure
    does not cascade into a noisy Dagster retry loop.
    """

    as_of = date.fromisoformat(context.partition_key)
    selected_provider_key = build_provider(get_settings()).provider_key
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        with SqlAlchemyUnitOfWork(factory) as uow:
            stored_request = uow.provider_requests.get_by_logical_key(
                provider_key=selected_provider_key,
                dataset_key="etf_instruments",
                request_key=f"instruments-{as_of.isoformat()}",
            )
        if stored_request is None or stored_request.status == "failed":
            context.log.warning(
                "etf_instruments: upstream attempt failed or missing for %s; "
                "skipping core.instruments upsert",
                as_of.isoformat(),
            )
            return dg.MaterializeResult(
                metadata={
                    "row_count": 0,
                    "skipped": True,
                    "reason": "upstream attempt failed or missing",
                    "as_of": as_of.isoformat(),
                    "partition_key": context.partition_key,
                }
            )
        count = upsert_etf_instruments(
            factory,
            as_of=as_of,
            provider_key=selected_provider_key,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_instruments: upserted %s rows for as_of=%s",
        count,
        as_of.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "row_count": count,
            "as_of": as_of.isoformat(),
            "partition_key": context.partition_key,
            "skipped": False,
        }
    )


_DEFAULT_DAILY_BARS_START = date(2026, 7, 23)
_DEFAULT_DAILY_BARS_END = date(2026, 7, 30)


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    deps=[etf_instruments_raw],
    partitions_def=_ETF_INPUT_SNAPSHOT_PARTITIONS,
)
def etf_daily_bars_raw(
    context,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dg.MaterializeResult:
    """Persist the PR-02 three-layer evidence bundle for ETF daily bars.

    Calls the configured Provider for the personal ETF universe
    (the symbols declared in ``config/personal-universe.yaml``) over
    the one-day window ``[trade_date, trade_date]`` where
    ``trade_date`` is the Dagster partition key, hands the request /
    attempt / batch triple to
    :func:`invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw`,
    and surfaces the storage-assigned UUIDs through Dagster metadata.

    Depends on :func:`etf_instruments_raw` so the canonical
    ``core.instruments`` rows exist by the time the downstream
    upsert runs (the daily-bars upsert resolves
    ``symbol -> core.instruments.id`` via the partial unique business
    key). A failed attempt persists the request + attempt only — no
    batch row is created.

    The partition definition is shared with :func:`etf_input_snapshot`
    and :func:`personal_candidate_pool` so the trade date the Provider
    is asked for is always the snapshot's partition date, and
    ``personal_candidate_pool`` has a partition-aligned input.
    """

    provider = build_provider(get_settings())
    settings = get_settings()
    trade_date = date.fromisoformat(context.partition_key)
    if (start_date is not None and start_date != trade_date) or (
        end_date is not None and end_date != trade_date
    ):
        raise ValueError("daily-bars date arguments must match the partition date")
    start = trade_date
    end = trade_date
    universe = load_personal_universe(settings.personal_universe_path)
    symbols = list(universe.symbols)

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        result = write_etf_daily_bars_raw(
            provider,
            factory,
            symbols=symbols,
            start_date=start,
            end_date=end,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_daily_bars_raw: provider=%s request=%s attempt=%s batch=%s "
        "status=%s records=%s window=%s..%s",
        provider.provider_key,
        result.request_id,
        result.attempt_id,
        result.batch_id,
        result.request_status,
        result.record_count,
        start.isoformat(),
        end.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "provider": provider.provider_key,
            "request_id": str(result.request_id),
            "attempt_id": str(result.attempt_id),
            "batch_id": str(result.batch_id) if result.batch_id else "",
            "request_status": result.request_status,
            "attempt_status": result.attempt_status,
            "record_count": result.record_count,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "partition_key": context.partition_key,
            "symbol_count": len(symbols),
        }
    )


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    deps=[etf_daily_bars_raw],
    partitions_def=_ETF_INPUT_SNAPSHOT_PARTITIONS,
)
def etf_daily_bars(
    context,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dg.MaterializeResult:
    """Upsert standardized ETF daily bars into ``core.daily_bars``.

    Depends on :func:`etf_daily_bars_raw` and re-opens a fresh
    transaction to read the persisted attempt's
    ``response_payload_json`` sidecar. The records are deserialized,
    the real ``core.instruments.id`` is resolved per ``symbol``, and
    the resulting :class:`invest_domain.market_data.models.DailyBar`
    list is handed to
    :meth:`invest_storage.SqlAlchemyDailyBarRepository.upsert_many`.
    The repository applies the ADR-0006 §3 revision rules: identical
    business content is a no-op, content change increments the
    revision.

    If the upstream attempt failed the asset surfaces a
    :class:`MaterializeResult` with ``inserted=0`` and a ``skipped``
    note rather than raising, mirroring the etf_instruments asset's
    "no retry loop on contract failure" stance.

    The partition definition is shared with :func:`etf_input_snapshot`
    and :func:`personal_candidate_pool` so the trade date the
    downstream Candidate Pool asset consumes is always the snapshot
    partition date.
    """

    provider = build_provider(get_settings())
    settings = get_settings()
    trade_date = date.fromisoformat(context.partition_key)
    if (start_date is not None and start_date != trade_date) or (
        end_date is not None and end_date != trade_date
    ):
        raise ValueError("daily-bars date arguments must match the partition date")
    start = trade_date
    end = trade_date
    universe = load_personal_universe(settings.personal_universe_path)
    symbols = list(universe.symbols)
    request_key = make_daily_bars_request_key(start, end, symbols)

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        with SqlAlchemyUnitOfWork(factory) as uow:
            stored_request = uow.provider_requests.get_by_logical_key(
                provider_key=provider.provider_key,
                dataset_key="etf_daily_bars",
                request_key=request_key,
            )
        if stored_request is None or stored_request.status == "failed":
            context.log.warning(
                "etf_daily_bars: upstream attempt failed or missing for %s; "
                "skipping core.daily_bars upsert",
                request_key,
            )
            return dg.MaterializeResult(
                metadata={
                    "inserted": 0,
                    "skipped": 0,
                    "skipped_asset": True,
                    "reason": "upstream attempt failed or missing",
                    "request_key": request_key,
                }
            )
        summary = upsert_etf_daily_bars(
            factory,
            provider_key=provider.provider_key,
            dataset_key="etf_daily_bars",
            request_key=request_key,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_daily_bars: inserted=%s skipped=%s total=%s for window=%s..%s",
        summary.inserted,
        summary.skipped,
        summary.total,
        start.isoformat(),
        end.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "inserted": summary.inserted,
            "skipped": summary.skipped,
            "total": summary.total,
            "request_key": request_key,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "partition_key": context.partition_key,
        }
    )


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    deps=[etf_instruments],
    partitions_def=_ETF_INPUT_SNAPSHOT_PARTITIONS,
)
def etf_input_snapshot(context) -> dg.MaterializeResult:
    """Build the personal-universe-aligned :class:`InputSnapshot` for the partition.

    Loads ``config/personal-universe.yaml`` via
    :func:`invest_pipeline.personal_universe.load_personal_universe`,
    resolves each configured symbol against exactly one ETF
    :class:`Instrument` in ``core.instruments`` via
    :func:`invest_pipeline.personal_universe.resolve_personal_universe`,
    and persists the resulting ``instrument_ids`` as the
    :class:`InputSnapshot` for the partition date. The resolver
    guarantees:

    * each symbol maps to **exactly one** active ETF on SSE / SZSE;
    * missing, invalid (non-ETF / non-SSE / non-SZSE) and ambiguous
      (multiple valid candidates) symbols raise a
      :class:`PersonalUniverseError` subclass so a stale personal
      universe file is surfaced loudly rather than silently
      producing a partial snapshot;
    * the snapshot ``row_count`` equals ``len(universe.symbols)`` so
      the downstream :func:`personal_candidate_pool` asset receives
      exactly the personal universe it expects.

    Business trade date comes from ``context.partition_key`` only;
    a back-fill run for a historical partition cannot silently
    re-target today's data.
    """

    from invest_storage import SqlAlchemyUnitOfWork

    snapshot_date = date.fromisoformat(context.partition_key)
    settings = get_settings()
    universe = load_personal_universe(settings.personal_universe_path)

    engine = build_engine(settings.database_url)
    factory = session_factory(engine)
    try:

        def _uow_factory() -> Any:
            return SqlAlchemyUnitOfWork(factory)

        with _uow_factory() as uow:

            def _lookup(symbol: str) -> Sequence[Instrument]:
                rows = uow.session.scalars(
                    select(InstrumentRow).where(InstrumentRow.symbol == symbol)
                ).all()
                return [_row_to_instrument(row) for row in rows]

            resolved = resolve_personal_universe(universe, _lookup)

        snapshot = create_input_snapshot(
            uow_factory=_uow_factory,
            snapshot_date=snapshot_date,
            instrument_ids=list(resolved.instrument_ids),
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_input_snapshot: snapshot_date=%s row_count=%s content_hash=%s universe_size=%s",
        snapshot.snapshot_date.isoformat(),
        snapshot.row_count,
        snapshot.content_hash,
        len(universe.symbols),
    )
    return dg.MaterializeResult(
        metadata={
            "snapshot_id": str(snapshot.id),
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "partition_key": context.partition_key,
            "row_count": snapshot.row_count,
            "content_hash": snapshot.content_hash,
            "universe_size": len(universe.symbols),
        }
    )


# Reuse the upstream daily partition definition so the partition dates /
# range are guaranteed to align with the etf_input_snapshot asset.
_PERSONAL_CANDIDATE_POOL_PARTITIONS = _ETF_INPUT_SNAPSHOT_PARTITIONS


@dg.asset(
    group_name="candidate_pool",
    compute_kind="python",
    deps=[etf_input_snapshot, etf_daily_bars],
    partitions_def=_PERSONAL_CANDIDATE_POOL_PARTITIONS,
)
def personal_candidate_pool(context) -> dg.MaterializeResult:
    """Run the personal Candidate Pool service for the partition trade date.

    PR-3 slice 2: a Dagster-only wrapper around the existing
    :func:`invest_pipeline.candidate_pool_service.calculate_and_publish_candidate_pool`
    service. The asset:

    * Reads ``context.partition_key`` as the trade date (no
      ``date.today()`` fallback) so a back-fill run for a historical
      partition cannot silently re-target today's data.
    * Resolves the persisted :class:`InputSnapshot` for that date via
      :meth:`InputSnapshotRepository.list_by_date`; raises
      :class:`CandidatePoolSnapshotNotFoundError` when no snapshot row
      exists so the upstream ``etf_input_snapshot`` asset can be
      re-materialised before retrying.
    * Loads ``config/candidate-pool-personal.yaml`` through
      :func:`load_candidate_pool_policy` and delegates the calculator +
      persistence + state-machine transitions to the service.
    * Surfaces ``run_id``, ``trade_date``, ``status``, ``input_count``,
      ``included_count`` and ``item_count`` through Dagster metadata.

    Depends on :func:`etf_input_snapshot` so the snapshot row exists by
    the time this asset runs and on :func:`etf_daily_bars` so the daily
    bars the calculator consumes are already persisted for the
    partition date.
    """

    trade_date = date.fromisoformat(context.partition_key)
    settings = get_settings()
    policy = load_candidate_pool_policy(settings.candidate_pool_policy_path)

    engine = build_engine(settings.database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        def _uow_factory() -> Any:
            return SqlAlchemyUnitOfWork(factory)

        with _uow_factory() as lookup_uow:
            snapshots = lookup_uow.input_snapshot_repository.list_by_date(trade_date)
        if not snapshots:
            raise CandidatePoolSnapshotNotFoundError(
                f"no InputSnapshot persisted for trade_date="
                f"{trade_date.isoformat()}; re-materialise etf_input_snapshot "
                "for this partition before retrying personal_candidate_pool"
            )
        snapshot_id = snapshots[-1].id

        result = calculate_and_publish_candidate_pool(
            uow_factory=_uow_factory,
            trade_date=trade_date,
            snapshot_id=snapshot_id,
            policy=policy,
        )
    finally:
        engine.dispose()

    context.log.info(
        "personal_candidate_pool: trade_date=%s snapshot_id=%s status=%s run_id=%s included=%s/%s",
        result.run.trade_date.isoformat(),
        result.run.input_snapshot_id,
        result.run.status.value,
        result.run.id,
        result.run.included_count,
        result.run.input_row_count,
    )
    return dg.MaterializeResult(
        metadata={
            "run_id": str(result.run.id),
            "trade_date": result.run.trade_date.isoformat(),
            "status": result.run.status.value,
            "input_count": result.run.input_row_count,
            "included_count": result.run.included_count,
            "item_count": len(result.result.items),
        }
    )


# Stage 4B: A-share stock market-data chain.
#
# The chain reuses the PR-02 / PR-05 / PR-06 service modules — there is
# no stock-specific variant — and routes them through the dedicated
# Tushare ``StockTushareProvider`` via the ``build_stock_provider``
# factory. Four assets make up the chain; their only relationship with
# the ETF slice is the shared PR-02 three-layer evidence bundle, which
# is keyed by ``(provider_key, dataset_key, request_key)`` so the two
# chains cannot collide.


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def stock_instruments_raw(context) -> dg.MaterializeResult:
    """Persist the PR-02 three-layer evidence bundle for A-share master data.

    Calls the Tushare ``StockTushareProvider`` and hands the resulting
    ``(ProviderRequest, ProviderAttempt, ProviderBatch)`` triple to
    :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`,
    which is provider-agnostic and only depends on the evidence tuple.
    The provider stamps ``dataset_key="stock_instruments"`` on the
    persisted request so the downstream :func:`stock_instruments` asset
    can resolve the matching attempt via
    ``(provider_key="tushare", dataset_key="stock_instruments",
    request_key="instruments-{as_of}")`` without colliding with the
    parallel ETF slice.

    The asset's ``provider_key`` is fixed to ``"tushare"`` because the
    A-share master-data surface is exposed only by the Tushare adapter
    today; routing through ``build_stock_provider`` keeps the gate
    consistent with the PR-1B / ADR-0011 contract (explicit
    enabled + token check before any HTTP traffic).
    """

    as_of = date.fromisoformat(context.partition_key)
    provider = build_stock_provider(get_settings())
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        result = write_etf_instruments_raw(
            provider,
            factory,
            as_of=as_of,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "stock_instruments_raw: provider=%s request=%s attempt=%s batch=%s "
        "status=%s records=%s as_of=%s",
        provider.provider_key,
        result.request_id,
        result.attempt_id,
        result.batch_id,
        result.request_status,
        result.record_count,
        as_of.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "provider": provider.provider_key,
            "dataset_key": "stock_instruments",
            "request_id": str(result.request_id),
            "attempt_id": str(result.attempt_id),
            "batch_id": str(result.batch_id) if result.batch_id else "",
            "request_status": result.request_status,
            "attempt_status": result.attempt_status,
            "record_count": result.record_count,
            "as_of": as_of.isoformat(),
            "partition_key": context.partition_key,
        }
    )


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    deps=[stock_instruments_raw],
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def stock_instruments(context) -> dg.MaterializeResult:
    """Upsert standardized A-share instruments into ``core.instruments``.

    Reuses the provider-agnostic
    :func:`invest_pipeline.etf_instruments.upsert_etf_instruments` with
    explicit ``provider_key="tushare"`` and
    ``dataset_key="stock_instruments"`` so the upstream request lookup
    resolves the attempt the partitioned raw write just persisted —
    the service is dataset-agnostic, only the logical-key tuple
    disambiguates which attempt is consumed. The ``request_key`` the
    service derives (``instruments-{as_of}``) matches the
    :meth:`StockTushareProvider.fetch_instruments` request shape.

    If the upstream request is missing or in ``failed`` status the
    asset surfaces a :class:`MaterializeResult` with ``row_count=0``
    and a ``skipped`` note rather than raising, mirroring the
    :func:`etf_instruments` asset's "no retry loop on contract failure"
    stance.
    """

    as_of = date.fromisoformat(context.partition_key)
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        with SqlAlchemyUnitOfWork(factory) as uow:
            stored_request = uow.provider_requests.get_by_logical_key(
                provider_key="tushare",
                dataset_key="stock_instruments",
                request_key=f"instruments-{as_of.isoformat()}",
            )
        if stored_request is None or stored_request.status == "failed":
            context.log.warning(
                "stock_instruments: upstream attempt failed or missing for %s; "
                "skipping core.instruments upsert",
                as_of.isoformat(),
            )
            return dg.MaterializeResult(
                metadata={
                    "row_count": 0,
                    "skipped": True,
                    "reason": "upstream attempt failed or missing",
                    "as_of": as_of.isoformat(),
                    "partition_key": context.partition_key,
                }
            )
        count = upsert_etf_instruments(
            factory,
            as_of=as_of,
            provider_key="tushare",
            dataset_key="stock_instruments",
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "stock_instruments: upserted %s rows for as_of=%s",
        count,
        as_of.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "row_count": count,
            "as_of": as_of.isoformat(),
            "partition_key": context.partition_key,
            "skipped": False,
        }
    )


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    deps=[stock_instruments],
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def stock_daily_bars_raw(context) -> dg.MaterializeResult:
    """Persist the PR-02 three-layer evidence bundle for A-share daily bars.

    Wires the dedicated Tushare
    :meth:`StockTushareProvider.fetch_daily_bars_by_trade_date` capability
    through :func:`invest_pipeline.stock_daily_bars.write_stock_daily_bars_raw_with_tdx_fallback`:
    a single by-date ``daily`` request that returns every A-share daily
    bar for the partition's ``trade_date``, with the opt-in TDX offline
    fallback consulted only after a *failed* Tushare attempt. The
    orchestration preserves Tushare as the primary / default behaviour:
    a successful or partial Tushare run is always the answer, even
    when ``INVEST_PIPELINE_TDX_OFFLINE_ENABLED=true``; the offline
    reader never silently overwrites a degraded primary read. The
    Tushare provider stamps
    ``dataset_key='stock_daily_bars_by_date'`` /
    ``request_key='daily-bars-by-date-{trade_date.isoformat()}'`` on the
    persisted request and the offline fallback stamps the distinct
    ``(provider_key='tdx_offline', dataset_key='stock_daily_bars',
    request_key='daily-bars-by-date-{trade_date.isoformat()}')`` tuple,
    so the two requests cannot collide in ``raw.provider_requests`` and
    the downstream :func:`stock_daily_bars` asset can resolve
    whichever provider produced the successful attempt via the
    logical-key triplet alone — no Dagster metadata, no second network
    call.

    The Tushare ``StockTushareProvider`` is wired via
    :func:`invest_pipeline.provider_factory.build_stock_provider`; the
    fallback reads :class:`TdxOfflineSettings` from the environment
    (``INVEST_PIPELINE_TDX_OFFLINE_*``) and fails closed on an empty
    persisted ``STOCK`` universe. The asset depends on
    :func:`stock_instruments` so the canonical ``core.instruments``
    rows exist by the time the downstream upsert runs (the daily-bars
    upsert resolves ``(symbol, exchange) -> core.instruments.id`` via
    the partial unique business key).
    """

    settings = get_settings()
    trade_date = date.fromisoformat(context.partition_key)

    provider = build_stock_provider(settings)
    engine = build_engine(settings.database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        from invest_pipeline.adapters.tdx_offline.config import TdxOfflineSettings
        from invest_pipeline.stock_daily_bars import (
            write_stock_daily_bars_raw_with_tdx_fallback,
        )

        result = write_stock_daily_bars_raw_with_tdx_fallback(
            provider,
            factory,
            trade_date=trade_date,
            tdx_settings=TdxOfflineSettings(),
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "stock_daily_bars_raw: provider=%s request=%s attempt=%s batch=%s "
        "status=%s records=%s trade_date=%s",
        provider.provider_key,
        result.request_id,
        result.attempt_id,
        result.batch_id,
        result.request_status,
        result.record_count,
        trade_date.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "provider": provider.provider_key,
            "dataset_key": "stock_daily_bars_by_date",
            "request_id": str(result.request_id),
            "attempt_id": str(result.attempt_id),
            "batch_id": str(result.batch_id) if result.batch_id else "",
            "request_status": result.request_status,
            "attempt_status": result.attempt_status,
            "record_count": result.record_count,
            "trade_date": trade_date.isoformat(),
            "partition_key": context.partition_key,
        }
    )


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    deps=[stock_daily_bars_raw],
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def stock_daily_bars(context) -> dg.MaterializeResult:
    """Upsert standardized A-share daily bars into ``core.daily_bars``.

    Depends on :func:`stock_daily_bars_raw` and re-opens a fresh
    transaction to read the persisted attempt's
    ``response_payload_json`` sidecar. The request lookup walks the
    Stage 4B fallback candidates in priority order — the
    :func:`invest_pipeline.provider_factory.build_stock_provider`
    primary first, then the opt-in ``tdx_offline`` fallback — and
    reads whichever persisted request succeeded. The resolution uses
    the ``(provider_key, dataset_key, request_key)`` logical-key
    triplet alone, so the asset does not have to consult Dagster
    metadata or issue a second network call to learn which provider
    produced the successful attempt. The two candidates share the
    by-date ``request_key`` but are distinguished by their
    ``provider_key`` / ``dataset_key`` pair:

    * ``("tushare", "stock_daily_bars_by_date",
      "daily-bars-by-date-{trade_date}")`` — the Tushare primary.
    * ``("tdx_offline", "stock_daily_bars",
      "daily-bars-by-date-{trade_date}")`` — the offline fallback.

    The sidecar records are deserialized, the real
    ``core.instruments.id`` is resolved per ``(symbol, exchange)`` (the
    exchange is read from the sidecar, NOT inferred from the code
    prefix), and the resulting
    :class:`invest_domain.market_data.models.DailyBar` list is handed
    to :func:`invest_pipeline.stock_daily_bars.upsert_stock_daily_bars`.
    The repository applies the ADR-0006 §3 revision rules: identical
    business content is a no-op, content change increments the
    revision.

    If both persisted requests are missing or in ``failed`` status the
    asset surfaces a :class:`MaterializeResult` with ``inserted=0``
    and a ``skipped`` note rather than raising, mirroring the
    :func:`etf_daily_bars` asset's "no retry loop on contract failure"
    stance.
    """

    settings = get_settings()
    trade_date = date.fromisoformat(context.partition_key)
    request_key = f"daily-bars-by-date-{trade_date.isoformat()}"

    primary_provider = build_stock_provider(settings)
    engine = build_engine(settings.database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        from invest_pipeline.stock_daily_bars import (
            TDX_OFFLINE_FALLBACK_DATASET_KEY,
            TDX_OFFLINE_FALLBACK_PROVIDER_KEY,
        )

        candidates = [
            (primary_provider.provider_key, "stock_daily_bars_by_date"),
            (TDX_OFFLINE_FALLBACK_PROVIDER_KEY, TDX_OFFLINE_FALLBACK_DATASET_KEY),
        ]
        with SqlAlchemyUnitOfWork(factory) as uow:
            stored_request = None
            resolved_provider_key: str | None = None
            resolved_dataset_key: str | None = None
            for candidate_provider_key, candidate_dataset_key in candidates:
                stored = uow.provider_requests.get_by_logical_key(
                    provider_key=candidate_provider_key,
                    dataset_key=candidate_dataset_key,
                    request_key=request_key,
                )
                if stored is not None and stored.status != "failed":
                    stored_request = stored
                    resolved_provider_key = candidate_provider_key
                    resolved_dataset_key = candidate_dataset_key
                    break
        if stored_request is None:
            context.log.warning(
                "stock_daily_bars: upstream attempt failed or missing for %s; "
                "skipping core.daily_bars upsert",
                request_key,
            )
            return dg.MaterializeResult(
                metadata={
                    "inserted": 0,
                    "skipped": 0,
                    "skipped_asset": True,
                    "reason": "upstream attempt failed or missing",
                    "request_key": request_key,
                    "trade_date": trade_date.isoformat(),
                    "partition_key": context.partition_key,
                }
            )
        summary = upsert_stock_daily_bars(
            factory,
            provider_key=resolved_provider_key or "",
            dataset_key=resolved_dataset_key or "",
            request_key=request_key,
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "stock_daily_bars: provider=%s inserted=%s skipped=%s total=%s for trade_date=%s",
        resolved_provider_key,
        summary.inserted,
        summary.skipped,
        summary.total,
        trade_date.isoformat(),
    )
    return dg.MaterializeResult(
        metadata={
            "provider": resolved_provider_key or "",
            "inserted": summary.inserted,
            "skipped": summary.skipped,
            "total": summary.total,
            "request_key": request_key,
            "trade_date": trade_date.isoformat(),
            "partition_key": context.partition_key,
        }
    )


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    deps=[stock_instruments],
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def stock_input_snapshot(context) -> dg.MaterializeResult:
    """Build the A-share :class:`InputSnapshot` for the partition trade date.

    Derives the stock universe dynamically from the persisted
    ``core.instruments`` table through
    :func:`invest_pipeline.market_breadth_service.list_active_stock_instrument_ids`:
    the helper queries the UoW session for every active ``STOCK`` row
    (``ETF`` / ``INDEX`` / inactive / delisted rows are filtered out at
    the database level) and returns the storage-side ``instrument_id``
    UUIDs in deterministic ``(exchange, symbol, id)`` order. The
    explicit ``config/stock-universe.yaml`` is no longer consulted —
    the persisted ``core.instruments`` rows that the upstream
    ``stock_instruments`` asset materialises are the authoritative
    universe, and the ``Settings.stock_universe_path`` field is
    preserved only for back-compat with the static-universe wiring
    tests.

    The helper fails closed on an empty persisted active ``STOCK``
    universe by raising :class:`StockUniverseEmptyError`; the asset
    propagates the error so a misconfigured upstream
    ``stock_instruments`` materialisation surfaces as a hard Dagster
    failure rather than a partial snapshot. The partition trade date
    comes from ``context.partition_key`` only; no ``date.today()``
    fallback.
    """

    from invest_storage import SqlAlchemyUnitOfWork

    snapshot_date = date.fromisoformat(context.partition_key)

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:

        def _uow_factory() -> Any:
            return SqlAlchemyUnitOfWork(factory)

        with _uow_factory() as uow:
            instrument_ids = list_active_stock_instrument_ids(uow)

        snapshot = create_input_snapshot(
            uow_factory=_uow_factory,
            snapshot_date=snapshot_date,
            instrument_ids=instrument_ids,
        )
    finally:
        engine.dispose()

    context.log.info(
        "stock_input_snapshot: snapshot_date=%s row_count=%s content_hash=%s universe_size=%s",
        snapshot.snapshot_date.isoformat(),
        snapshot.row_count,
        snapshot.content_hash,
        len(instrument_ids),
    )
    return dg.MaterializeResult(
        metadata={
            "snapshot_id": str(snapshot.id),
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "partition_key": context.partition_key,
            "row_count": snapshot.row_count,
            "content_hash": snapshot.content_hash,
            "universe_size": len(instrument_ids),
        }
    )


@dg.asset(
    group_name="stock_market_data",
    compute_kind="python",
    deps=[stock_input_snapshot, stock_daily_bars],
    partitions_def=_STOCK_MARKET_DATA_PARTITIONS,
)
def market_breadth_snapshot(context) -> dg.MaterializeResult:
    """Materialise the Stage 4B Market Breadth observation for the partition.

    Resolves the persisted :class:`InputSnapshot` for the partition
    trade date, hands it to
    :func:`invest_pipeline.market_breadth_service.calculate_and_publish_market_breadth`
    (which reads the rolling 20-day window of ``core.daily_bars`` for
    every resolved instrument, computes the 20-day moving average
    from the available closes, and persists the resulting
    :class:`MarketObservationSnapshot` through the existing
    ``market_observation_snapshots`` repository), and surfaces the
    result through Dagster metadata.

    The asset surfaces a :class:`MaterializeResult` with
    ``skipped=True`` / ``invalid=True`` and a human-readable
    ``reason`` rather than raising whenever the persisted snapshot
    is not ``COMPLETE`` / ``FRESH`` — i.e. no input snapshot exists
    for the partition, the breadth service reports insufficient
    20-day history (the common "freshly-listed symbol" / mixed
    valid+missing case), or the snapshot is otherwise not a clean
    success. ``skipped=False`` is reserved for the
    ``quality_status == COMPLETE`` / ``freshness_status == FRESH``
    success path so Dagster never enters a retry loop on a
    contract-failure outcome.
    """

    from invest_domain.research.models import FreshnessStatus, QualityStatus
    from invest_storage import SqlAlchemyUnitOfWork

    trade_date = date.fromisoformat(context.partition_key)

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:

        def _uow_factory() -> Any:
            return SqlAlchemyUnitOfWork(factory)

        with _uow_factory() as uow:
            snapshots = uow.input_snapshot_repository.list_by_date(trade_date)
        if not snapshots:
            raise MarketBreadthInsufficientDataError(
                f"no stock InputSnapshot persisted for trade_date="
                f"{trade_date.isoformat()}; re-materialise stock_input_snapshot "
                "for this partition before retrying market_breadth_snapshot"
            )
        # Use the most recently persisted snapshot for the date so a
        # same-day rerun picks up the latest universe without
        # re-allocating storage-side identity.
        input_snapshot = snapshots[-1]
        result = calculate_and_publish_market_breadth(
            uow_factory=_uow_factory,
            input_snapshot=input_snapshot,
            as_of=trade_date,
        )
    except MarketBreadthInsufficientDataError as exc:
        context.log.warning(
            "market_breadth_snapshot: insufficient 20-day history for %s; "
            "skipping without retry: %s",
            trade_date.isoformat(),
            exc,
        )
        return dg.MaterializeResult(
            metadata={
                "as_of": trade_date.isoformat(),
                "partition_key": context.partition_key,
                "skipped": True,
                "invalid": True,
                "reason": str(exc),
                "instrument_count": 0,
            }
        )
    finally:
        engine.dispose()

    quality = result.snapshot.quality_status
    freshness = result.snapshot.freshness_status
    if quality is QualityStatus.COMPLETE and freshness is FreshnessStatus.FRESH:
        context.log.info(
            "market_breadth_snapshot: trade_date=%s snapshot_id=%s instrument_count=%s "
            "quality=%s freshness=%s",
            trade_date.isoformat(),
            result.snapshot.snapshot_id,
            result.instrument_count,
            quality.value,
            freshness.value,
        )
        return dg.MaterializeResult(
            metadata={
                "as_of": trade_date.isoformat(),
                "partition_key": context.partition_key,
                "snapshot_id": result.snapshot.snapshot_id,
                "input_snapshot_id": str(result.snapshot.input_snapshot_id),
                "instrument_count": result.instrument_count,
                "quality_status": quality.value,
                "freshness_status": freshness.value,
                "skipped": False,
                "invalid": False,
            }
        )

    # Non-COMPLETE / non-FRESH snapshot: the breadth service refused
    # to publish a partial snapshot and recorded a deterministic
    # ``INVALID / FAILED`` row (or, theoretically, ``PARTIAL`` /
    # ``STALE``). Surface it as a skipped / invalid asset result so
    # Dagster does not enter a retry loop on a contract-failure
    # outcome. ``instrument_count`` is reported unchanged so operators
    # can audit how many instruments the service considered before
    # fail-closing.
    reason = (
        f"breadth snapshot for {trade_date.isoformat()} is "
        f"{quality.value}/{freshness.value}: the breadth service "
        "refused to publish a partial snapshot because at least one "
        "input-snapshot instrument lacked a valid 20-day history; "
        "the persisted snapshot is the deterministic INVALID/FAILED "
        "shape and the asset surfaces it as skipped / invalid"
    )
    context.log.warning(
        "market_breadth_snapshot: %s",
        reason,
    )
    return dg.MaterializeResult(
        metadata={
            "as_of": trade_date.isoformat(),
            "partition_key": context.partition_key,
            "snapshot_id": result.snapshot.snapshot_id,
            "input_snapshot_id": str(result.snapshot.input_snapshot_id),
            "instrument_count": result.instrument_count,
            "quality_status": quality.value,
            "freshness_status": freshness.value,
            "skipped": True,
            "invalid": quality is QualityStatus.INVALID,
            "reason": reason,
        }
    )
