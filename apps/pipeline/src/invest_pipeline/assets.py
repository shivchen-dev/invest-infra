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
from invest_pipeline.personal_universe import (
    load_personal_universe,
    resolve_personal_universe,
)
from invest_pipeline.provider_factory import build_provider

_ETF_INPUT_SNAPSHOT_PARTITIONS = dg.DailyPartitionsDefinition(
    start_date="2026-07-23"
)


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


@dg.asset(group_name="market_data", compute_kind="python")
def etf_instruments_raw(context) -> dg.MaterializeResult:
    """Persist the PR-02 three-layer evidence bundle for ETF master data.

    Calls the ``fixture_dev`` adapter, hands the request / attempt /
    batch triple to :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`,
    and surfaces the storage-assigned UUIDs through Dagster metadata.

    A failed attempt persists the request + attempt only — no batch row
    is created. The downstream :func:`etf_instruments` asset inspects
    the persisted state to decide whether to upsert standardized
    records or skip with a note.
    """

    provider = build_provider(get_settings())
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        result = write_etf_instruments_raw(
            provider,
            factory,
            as_of=date.today(),
            unit_of_work_factory=SqlAlchemyUnitOfWork,
        )
    finally:
        engine.dispose()

    context.log.info(
        "etf_instruments_raw: provider=%s request=%s attempt=%s batch=%s status=%s records=%s",
        provider.provider_key,
        result.request_id,
        result.attempt_id,
        result.batch_id,
        result.request_status,
        result.record_count,
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
        }
    )


@dg.asset(
    group_name="market_data",
    compute_kind="python",
    deps=[etf_instruments_raw],
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

    If the upstream attempt failed the asset surfaces a
    :class:`MaterializeResult` with ``row_count=0`` and a
    ``skipped`` note rather than raising, so a contract-test failure
    does not cascade into a noisy Dagster retry loop.
    """

    as_of = date.today()
    selected_provider_key = build_provider(get_settings()).provider_key
    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    try:
        from invest_storage import SqlAlchemyUnitOfWork

        with SqlAlchemyUnitOfWork(factory) as uow:
            stored_request = uow.provider_requests.get_by_logical_key(
                provider_key=selected_provider_key,
                dataset_key="instruments",
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
    request_key = (
        f"daily-bars-{start.isoformat()}-{end.isoformat()}-"
        f"{'-'.join(symbols)}"
    )

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
        "etf_input_snapshot: snapshot_date=%s row_count=%s content_hash=%s "
        "universe_size=%s",
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
            snapshots = lookup_uow.input_snapshot_repository.list_by_date(
                trade_date
            )
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
        "personal_candidate_pool: trade_date=%s snapshot_id=%s status=%s "
        "run_id=%s included=%s/%s",
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
