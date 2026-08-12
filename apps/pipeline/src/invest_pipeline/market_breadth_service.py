"""Pipeline application service for the Stage 4B Market Breadth slice.

This module implements the smallest complete ``Pipeline`` application
service for the Market Breadth vertical slice that:

* exposes a provider-agnostic
  :func:`list_active_stock_instrument_ids` helper that queries the
  ``UnitOfWork`` session for every active ``STOCK`` row in
  ``core.instruments`` (filtering out ``ETF`` / ``INDEX`` /
  inactive / delisted rows at the database level) and returns the
  storage-side ``instrument_id`` UUIDs in deterministic
  ``(exchange, symbol, id)`` order. The helper is the canonical
  dynamic-universe source for the ``stock_input_snapshot`` Dagster
  asset; it fails closed with :class:`StockUniverseEmptyError` when
  the persisted active ``STOCK`` universe is empty so a
  misconfigured upstream ``stock_instruments`` materialisation
  surfaces as a hard failure rather than a partial ``InputSnapshot``;
* preserves :func:`resolve_stock_instrument_ids` for explicit-universe
  callers (it resolves a hand-curated symbol set against active
  ``STOCK`` rows in ``core.instruments`` using the same lookup
  contract :func:`invest_pipeline.personal_universe.resolve_personal_universe`
  uses for ETFs, with the only difference that the resolver accepts
  ``STOCK`` instead of ``ETF``);
* persists the resolved ``instrument_ids`` as an :class:`InputSnapshot`
  for the partition trade date (the **same** :class:`InputSnapshot` the
  ``stock_input_snapshot`` Dagster asset materialises);
* for every resolved instrument, reads the latest ``core.daily_bars``
  rows over a rolling natural-day window wide enough to cover the most
  recent 20 valid trading days (``[as_of - 59, as_of]`` — see
  :data:`_BREADTH_LOOKBACK_NATURAL_DAYS`);
* computes the 20-day simple moving average from the closes of the
  **most recent 20 ``normal`` bars** in that window (weekends /
  holidays / suspended days are skipped by filtering on
  ``trading_status == "normal"`` and tail-slicing) and assembles one
  :class:`MarketBreadthInput` per instrument;
* delegates the breadth aggregation to the pure-domain builder
  :func:`invest_domain.analytics.market_breadth.build_market_breadth`;
* persists the resulting :class:`MarketObservationSnapshot` through
  the existing
  :class:`invest_storage.SqlAlchemyMarketObservationSnapshotRepository`
  (no new migration / table).

The service is deliberately Dagster-free — no asset / schedule / log
machinery — so it can be unit-tested with a hand-rolled fake UoW and
so the asset layer stays a thin wrapper. The as-of date is always
supplied by the caller (today: the Dagster partition key); the
service never reads ``date.today()`` so a back-fill run for a
historical partition cannot silently re-target today's data.

Failure modes are explicitly fail-closed:

* The universe loader, the resolver, and the breadth builder all raise
  on configuration / invariant violations and surface through the
  service's normal exception path.
* An instrument that lacks a complete 20-day bar history is filtered
  out of the breadth input; the service refuses to publish a
  ``COMPLETE`` snapshot when **any** instrument in the input snapshot
  could not build a valid breadth input. In that mixed-or-all
  filtered case the service hands an empty ``instruments`` sequence
  to the pure-domain builder so the resulting snapshot is the
  deterministic ``INVALID / FAILED`` shape, and
  ``instrument_count=0`` is reported so operators can audit that the
  universe was rejected rather than partially computed.
* When **every** instrument is filtered out — the common
  "freshly-listed symbol" case — the snapshot is still persisted with
  the same ``INVALID / FAILED`` shape so a partition with no 20-day
  history is auditable in storage. The asset layer surfaces
  ``skipped=True`` / ``invalid=True`` / ``reason`` metadata so Dagster
  does not enter a retry loop on a contract-failure outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from invest_domain.analytics.market_breadth import (
    TRADING_STATUS_NORMAL,
    TRADING_STATUS_SUSPENDED,
    TRADING_STATUS_UNKNOWN,
    MarketBreadthInput,
    build_market_breadth,
    build_market_breadth_v2,
)
from invest_domain.analytics.market_observations import MarketObservationSnapshot
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import Instrument, InstrumentType
from invest_domain.market_data.values import Adjust
from invest_storage.models import InstrumentRow
from invest_storage.repositories import StoredDailyBar, _row_to_instrument
from invest_storage.unit_of_work import UnitOfWork
from sqlalchemy import select
from sqlalchemy.orm import Session

UnitOfWorkFactory = Callable[[], UnitOfWork]

_MIN_BREADTH_HISTORY = 20

# Rolling natural-day window used to read ``core.daily_bars`` for the
# breadth MA20 calculation. The previous implementation queried only
# ``as_of - 19`` natural days, which yields fewer than 20 trading days
# whenever ``as_of`` falls on (or near) a weekend or public holiday —
# 19 contiguous calendar days contain at most ~14 trading days, and a
# long-holiday week can drop that further to ~10. The breadth builder
# then sees fewer than :data:`_MIN_BREADTH_HISTORY` ``normal`` bars and
# fails closed (every instrument is filtered → ``INVALID / FAILED``
# snapshot), so the Stage 4B pipeline silently produced an
# ``instrument_count=0`` snapshot for an otherwise-valid universe.
#
# 60 natural days covers ~8.5 calendar weeks, i.e. >=40 trading days,
# which is comfortably above the 20 needed for MA20 even after the
# worst Chinese-market holiday run (Spring Festival + National Day
# adjacent weeks). The repository call is still bounded by an inclusive
# ``[start_date, end_date]`` range; :func:`_select_breadth_input` then
# tail-slices to the most recent :data:`_MIN_BREADTH_HISTORY` ``normal``
# bars so the MA20 semantics are unchanged. ``_bars_in_window`` keeps
# the inclusive ``end_date`` and uses ``start_date = end_date - 59``
# so the 60th natural day before ``as_of`` is included on the boundary.
_BREADTH_LOOKBACK_NATURAL_DAYS = 60

_MIN_V2_BREADTH_HISTORY = 250
_V2_BREADTH_LOOKBACK_NATURAL_DAYS = 400
_V2_MA20_PERIOD = 20
_V2_MA60_PERIOD = 60

__all__ = [
    "MarketBreadthInsufficientDataError",
    "MarketBreadthPublishResult",
    "StockUniverseEmptyError",
    "calculate_and_publish_market_breadth",
    "calculate_and_publish_market_breadth_v2",
    "list_active_stock_instrument_ids",
    "resolve_stock_instrument_ids",
]


class MarketBreadthInsufficientDataError(ValueError):
    """Raised when no instrument survives the 20-day / MA20 filtering.

    The caller is expected to surface this as a fail-closed
    :class:`MaterializeResult` (with ``skipped=True`` and
    ``invalid=True`` metadata) rather than a Dagster retry loop.
    """


class StockUniverseEmptyError(ValueError):
    """Raised when the persisted active ``STOCK`` universe is empty.

    The dynamic-universe slice refuses to publish a non-empty
    :class:`InputSnapshot` for an empty universe — the asset would
    either fabricate ids or surface a generic empty-list error. The
    :class:`InputSnapshot` / market-observation contract requires at
    least one instrument, so the helper fails closed with a
    domain-specific exception that the asset layer propagates so a
    misconfigured upstream ``stock_instruments`` materialisation
    surfaces as a hard Dagster failure rather than a partial
    snapshot.
    """


@dataclass(frozen=True, slots=True)
class MarketBreadthPublishResult:
    """Return shape of :func:`calculate_and_publish_market_breadth`.

    The :class:`InputSnapshot` is the freshly-persisted stock input
    snapshot, the :class:`MarketObservationSnapshot` is the breadth
    snapshot handed to the Analytics repository, and ``instrument_count``
    surfaces how many instruments contributed valid breadth inputs (so
    operators can audit how many were dropped for missing 20-day
    history).
    """

    snapshot: MarketObservationSnapshot
    input_snapshot: InputSnapshot
    instrument_count: int


def resolve_stock_instrument_ids(
    uow: UnitOfWork,
    *,
    symbols: Sequence[str],
) -> list[UUID]:
    """Resolve the explicit universe symbols to active ``STOCK`` instrument ids.

    The lookup is structural: every symbol must map to **exactly one**
    active row in ``core.instruments`` whose ``instrument_type`` is
    :attr:`InstrumentType.STOCK` (and not ``ETF`` / ``INDEX``). Missing,
    ambiguous or non-stock matches raise :class:`ValueError` so a
    stale / misconfigured universe file is surfaced loudly rather than
    silently producing a partial snapshot.
    """

    if not symbols:
        raise ValueError("symbols must not be empty")
    session: Session = uow.session
    resolved: dict[str, UUID] = {}
    duplicates: set[str] = set()
    for symbol in symbols:
        if symbol in resolved:
            duplicates.add(symbol)
            continue
        rows = (
            session.scalars(
                select(InstrumentRow)
                .where(
                    InstrumentRow.symbol == symbol,
                    InstrumentRow.delist_date.is_(None),
                )
                .order_by(InstrumentRow.exchange.asc(), InstrumentRow.id.asc())
            )
            .all()
        )
        candidates: list[Instrument] = [
            _row_to_instrument(row) for row in rows
        ]
        stock_candidates = [
            instrument
            for instrument in candidates
            if instrument.instrument_type is InstrumentType.STOCK
            and instrument.is_active
        ]
        if not stock_candidates:
            raise ValueError(
                f"stock universe symbol {symbol!r} did not match any active "
                f"STOCK row in core.instruments; available types="
                f"{[candidate.instrument_type.value for candidate in candidates]}"
            )
        if len(stock_candidates) > 1:
            raise ValueError(
                f"stock universe symbol {symbol!r} is ambiguous: matched "
                f"{len(stock_candidates)} active STOCK rows in core.instruments"
            )
        candidate = stock_candidates[0]
        if candidate.instrument_id is None:
            raise ValueError(
                f"stock universe symbol {symbol!r} resolved to a STOCK row "
                "without a storage-side instrument_id"
            )
        resolved[symbol] = candidate.instrument_id.value
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(
            f"stock universe symbols must not contain duplicates: {joined}"
        )
    # Preserve the order declared by the universe loader so the
    # resulting ``instrument_ids`` matches the YAML author intent.
    return [resolved[symbol] for symbol in symbols]


def list_active_stock_instrument_ids(uow: UnitOfWork) -> list[UUID]:
    """Return every active ``STOCK`` row's storage ``instrument_id``.

    The lookup is structural and provider-agnostic: every row in
    ``core.instruments`` whose ``is_active`` flag is set, whose
    ``instrument_type`` is :attr:`InstrumentType.STOCK` and whose
    ``delist_date`` is still ``NULL`` contributes its storage-side
    primary key to the returned list. ``ETF`` / ``INDEX`` rows,
    inactive ``STOCK`` rows, and delisted ``STOCK`` rows are filtered
    out at the database level so the universe can never silently grow
    with non-stock rows or re-target a delisted ticker.

    The list is ordered by ``(exchange, symbol, id)`` so two back-to-back
    runs of the same partition yield byte-identical ``instrument_ids``
    and the resulting :class:`InputSnapshot` content hash stays
    deterministic across reruns. The ``id`` tiebreaker is defensive —
    the partial unique index ``uq_instruments_symbol_exchange_active``
    already guarantees ``(symbol, exchange)`` uniqueness for
    non-delisted rows, but pinning the ordering on the primary key
    keeps the result stable even if that invariant is ever relaxed.

    The helper bypasses
    :meth:`invest_storage.repositories.SqlAlchemyInstrumentRepository.list_active`
    on purpose: that repository method has a silent default
    ``limit=100`` which would truncate the A-share universe (the full
    active universe is well above 100 rows). Querying the UoW session
    directly with no row limit avoids the silent truncation and
    returns every active ``STOCK`` row in a single roundtrip. The
    session-level read is also provider-agnostic — no ``Provider`` /
    ``Client`` / network dependency leaks in.

    Parameters
    ----------
    uow:
        An open :class:`UnitOfWork` whose ``session`` is bound to the
        PostgreSQL ``core.instruments`` table. The caller is
        responsible for entering the UoW context and committing /
        rolling back; the helper only reads.

    Returns
    -------
    list[UUID]
        The storage-side ``core.instruments.id`` for every active
        ``STOCK`` row, in deterministic ``(exchange, symbol, id)``
        order. The list is empty only when no active ``STOCK`` row
        exists, which is treated as a fail-closed configuration error
        (see :class:`StockUniverseEmptyError`).

    Raises
    ------
    StockUniverseEmptyError
        When the persisted active ``STOCK`` universe is empty. The
        asset layer propagates this so a misconfigured upstream
        ``stock_instruments`` materialisation surfaces as a hard
        Dagster failure rather than a partial ``InputSnapshot``.
    """

    if uow is None:
        raise ValueError("uow must not be None")
    session: Session = uow.session
    stmt = (
        select(InstrumentRow)
        .where(
            InstrumentRow.is_active.is_(True),
            InstrumentRow.instrument_type == InstrumentType.STOCK.value,
            InstrumentRow.delist_date.is_(None),
        )
        .order_by(
            InstrumentRow.exchange.asc(),
            InstrumentRow.symbol.asc(),
            InstrumentRow.id.asc(),
        )
    )
    rows = session.scalars(stmt).all()
    # Defence in depth: the SQL ``where`` clause above is the primary
    # filter (so PostgreSQL can use the partial unique index and we
    # never pull non-stock rows over the wire), but the helper also
    # re-applies the same predicates in Python. This guards against
    # silent regressions if the SQL filter is ever relaxed (e.g. an
    # accidental drop of ``instrument_type == 'STOCK'``) and lets the
    # helper contract be unit-tested through a hand-rolled fake UoW
    # that returns rows verbatim. The order is preserved end-to-end
    # so the deterministic ``(exchange, symbol, id)`` ordering the
    # ``order_by`` clause produces on a real session matches what the
    # unit test sees when it pre-orders the mock row list.
    ids = [
        row.id
        for row in rows
        if row.id is not None
        and getattr(row, "is_active", False) is True
        and getattr(row, "instrument_type", None) == InstrumentType.STOCK.value
        and getattr(row, "delist_date", None) is None
    ]
    if not ids:
        raise StockUniverseEmptyError(
            "no active STOCK rows in core.instruments; the dynamic "
            "stock universe is empty so stock_input_snapshot cannot "
            "persist a non-empty InputSnapshot — re-materialise "
            "stock_instruments before retrying"
        )
    return ids


def _bars_in_window(
    uow: UnitOfWork,
    *,
    instrument_id: UUID,
    end_date: date,
) -> list[StoredDailyBar]:
    """Return the latest daily bars for ``instrument_id`` in the rolling window.

    The window is :data:`_BREADTH_LOOKBACK_NATURAL_DAYS` calendar days
    wide so weekends / public holidays can never shrink the returned
    sequence below :data:`_MIN_BREADTH_HISTORY` ``normal`` bars; the
    repository returns rows ordered by ``trade_date ASC`` (one per
    trading date, highest revision wins), so the **last** element is
    always the most recent bar and :func:`_select_breadth_input` can
    tail-slice safely.
    """

    start_date = end_date - timedelta(days=_BREADTH_LOOKBACK_NATURAL_DAYS - 1)
    return list(
        uow.daily_bars.list_latest_by_instrument_and_range(
            instrument_id=instrument_id,
            start_date=start_date,
            end_date=end_date,
            adjustment=Adjust.NONE,
        )
    )


def _bars_in_window_v2(
    uow: UnitOfWork,
    *,
    instrument_id: UUID,
    end_date: date,
) -> list[StoredDailyBar]:
    """Return daily bars for ``instrument_id`` in the v2 rolling window.

    The window is :data:`_V2_BREADTH_LOOKBACK_NATURAL_DAYS` calendar days
    wide to ensure 250 normal bars are available; the repository returns
    rows ordered by ``trade_date ASC`` (one per trading date, highest
    revision wins), so the **last** element is always the most recent bar
    and :func:`_select_breadth_input_v2` can tail-slice safely.
    """

    start_date = end_date - timedelta(days=_V2_BREADTH_LOOKBACK_NATURAL_DAYS - 1)
    return list(
        uow.daily_bars.list_latest_by_instrument_and_range(
            instrument_id=instrument_id,
            start_date=start_date,
            end_date=end_date,
            adjustment=Adjust.NONE,
        )
    )


def _select_breadth_input(
    *,
    instrument_id: UUID,
    bars: Sequence[StoredDailyBar],
    as_of: date,
) -> MarketBreadthInput | None:
    """Build a :class:`MarketBreadthInput` from the rolling 20-day bars.

    Returns ``None`` when any of ``close``, ``prev_close`` or
    ``ma20`` is missing / non-finite / non-positive, when the latest
    bar is not on ``as_of``, or when fewer than
    :data:`_MIN_BREADTH_HISTORY` ``normal`` bars are available in the
    rolling window. The 20-day moving average is computed from the
    **closing prices of the most recent :data:`_MIN_BREADTH_HISTORY`
    ``normal`` bars** — the window :func:`_bars_in_window` reads is
    wider than 20 calendar days so we explicitly tail-slice here,
    otherwise weekend / holiday gaps would inflate the MA20 with stale
    closes. The repository returns rows ordered by ``trade_date ASC``,
    so a plain ``[-_MIN_BREADTH_HISTORY:]`` tail-slices the freshest
    rows after filtering on ``trading_status == "normal"``.
    """

    if not bars:
        return None
    latest = bars[-1]
    if latest.trade_date != as_of:
        return None
    normal_bars = [bar for bar in bars if bar.trading_status == "normal"]
    if len(normal_bars) < _MIN_BREADTH_HISTORY:
        return None
    recent_normal_bars = normal_bars[-_MIN_BREADTH_HISTORY:]
    closes: list[Decimal] = []
    for bar in recent_normal_bars:
        value = bar.close
        if value is None or not value.is_finite() or value <= 0:
            return None
        closes.append(value)
    ma20 = sum(closes, Decimal(0)) / Decimal(len(closes))
    if not ma20.is_finite() or ma20 <= 0:
        return None
    if (
        latest.close is None
        or not latest.close.is_finite()
        or latest.close <= 0
    ):
        return None
    if (
        latest.prev_close is None
        or not latest.prev_close.is_finite()
        or latest.prev_close <= 0
    ):
        return None
    trading_status = _resolve_trading_status(latest.trading_status)
    return MarketBreadthInput(
        instrument_id=instrument_id,
        close=latest.close,
        prev_close=latest.prev_close,
        ma20=ma20,
        observed_date=as_of,
        trading_status=trading_status,
    )


def _resolve_trading_status(raw: str) -> str:
    if raw == TRADING_STATUS_NORMAL:
        return TRADING_STATUS_NORMAL
    if raw == TRADING_STATUS_SUSPENDED:
        return TRADING_STATUS_SUSPENDED
    return TRADING_STATUS_UNKNOWN


def _select_breadth_input_v2(
    *,
    instrument_id: UUID,
    bars: Sequence[StoredDailyBar],
    as_of: date,
) -> MarketBreadthInput | None:
    """Build a v2 :class:`MarketBreadthInput` from the rolling 250-day bars.

    Returns ``None`` when any of ``close``, ``prev_close``, ``high``,
    ``low`` is missing / non-finite / non-positive, when the latest
    bar is not on ``as_of``, or when fewer than
    :data:`_MIN_V2_BREADTH_HISTORY` ``normal`` bars are available in
    the rolling window.

    MA20 is computed from the **closing prices of the most recent 20
    normal bars**; MA60 is computed from the **closing prices of the
    most recent 60 normal bars**. ``is_new_high`` is ``True`` when the
    latest bar's ``high`` is the maximum of all 250 normal bars' highs.
    ``is_new_low`` is ``True`` when the latest bar's ``low`` is the
    minimum of all 250 normal bars' lows.
    """

    if not bars:
        return None
    latest = bars[-1]
    if latest.trade_date != as_of:
        return None
    normal_bars = [bar for bar in bars if bar.trading_status == "normal"]
    if len(normal_bars) < _MIN_V2_BREADTH_HISTORY:
        return None
    recent_normal_bars = normal_bars[-_MIN_V2_BREADTH_HISTORY:]

    closes_ma20 = []
    for bar in recent_normal_bars[-_V2_MA20_PERIOD:]:
        value = bar.close
        if value is None or not value.is_finite() or value <= 0:
            return None
        closes_ma20.append(value)
    ma20 = sum(closes_ma20, Decimal(0)) / Decimal(len(closes_ma20))
    if not ma20.is_finite() or ma20 <= 0:
        return None

    closes_ma60 = []
    for bar in recent_normal_bars[-_V2_MA60_PERIOD:]:
        value = bar.close
        if value is None or not value.is_finite() or value <= 0:
            return None
        closes_ma60.append(value)
    ma60 = sum(closes_ma60, Decimal(0)) / Decimal(len(closes_ma60))
    if not ma60.is_finite() or ma60 <= 0:
        return None

    if (
        latest.close is None
        or not latest.close.is_finite()
        or latest.close <= 0
    ):
        return None
    if (
        latest.prev_close is None
        or not latest.prev_close.is_finite()
        or latest.prev_close <= 0
    ):
        return None
    if latest.high is None or not latest.high.is_finite() or latest.high <= 0:
        return None
    if latest.low is None or not latest.low.is_finite() or latest.low <= 0:
        return None

    highs: list[Decimal] = []
    for bar in recent_normal_bars:
        if bar.high is None or not bar.high.is_finite() or bar.high <= 0:
            return None
        highs.append(bar.high)
    lows: list[Decimal] = []
    for bar in recent_normal_bars:
        if bar.low is None or not bar.low.is_finite() or bar.low <= 0:
            return None
        lows.append(bar.low)

    is_new_high = latest.high >= max(highs)
    is_new_low = latest.low <= min(lows)

    trading_status = _resolve_trading_status(latest.trading_status)
    return MarketBreadthInput(
        instrument_id=instrument_id,
        close=latest.close,
        prev_close=latest.prev_close,
        ma20=ma20,
        observed_date=as_of,
        trading_status=trading_status,
        ma60=ma60,
        is_new_high=is_new_high,
        is_new_low=is_new_low,
    )


def calculate_and_publish_market_breadth(
    *,
    uow_factory: UnitOfWorkFactory,
    input_snapshot: InputSnapshot,
    as_of: date,
) -> MarketBreadthPublishResult:
    """Calculate the breadth snapshot for ``as_of`` and persist it.

    The service is a thin orchestration layer over the existing
    ``invest_domain.analytics.market_breadth.build_market_breadth``
    builder and the pre-existing
    :class:`invest_storage.SqlAlchemyMarketObservationSnapshotRepository`
    write path — it never bypasses those contracts and never opens a
    new table or migration.

    Parameters
    ----------
    uow_factory:
        A callable that hands out a fresh :class:`UnitOfWork` for the
        breadth read path. The service only opens one UoW so the
        breadth computation sees a consistent slice of
        ``core.daily_bars``.
    input_snapshot:
        The stock :class:`InputSnapshot` previously persisted by the
        :func:`invest_pipeline.assets.stock_input_snapshot` asset. Its
        ``snapshot_date`` must equal ``as_of``; a mismatch is a
        configuration / partition-alignment error and is raised
        immediately.
    as_of:
        The business trade date for the breadth snapshot. The service
        derives the rolling 20-day window from this value and never
        falls back to ``date.today()``.

    Returns
    -------
    MarketBreadthPublishResult
        A value object carrying the freshly-persisted
        :class:`MarketObservationSnapshot`, the input snapshot that
        bound the universe, and the count of instruments that
        contributed valid breadth inputs.
    """

    if input_snapshot.snapshot_date != as_of:
        raise ValueError(
            f"as_of {as_of.isoformat()} does not match input_snapshot."
            f"snapshot_date {input_snapshot.snapshot_date.isoformat()}; "
            "the breadth service refuses to silently fall back to a "
            "different trade date"
        )

    with uow_factory() as uow:
        inputs: list[MarketBreadthInput] = []
        expected = len(input_snapshot.instrument_ids)
        for instrument_id in input_snapshot.instrument_ids:
            bars = _bars_in_window(
                uow,
                instrument_id=instrument_id,
                end_date=as_of,
            )
            breadth_input = _select_breadth_input(
                instrument_id=instrument_id,
                bars=bars,
                as_of=as_of,
            )
            if breadth_input is not None:
                inputs.append(breadth_input)
        # Fail-closed: if any input-snapshot instrument could not
        # build a valid 20-day breadth input (missing history, latest
        # bar not on as_of, non-positive close / prev_close / ma20,
        # ...) refuse to publish a partial ``COMPLETE`` snapshot and
        # hand the builder an empty instruments sequence so the
        # deterministic ``INVALID / FAILED`` shape is recorded
        # unchanged. ``instrument_count`` stays at zero so operators
        # can audit that the universe was rejected rather than
        # partially computed.
        if expected > 0 and len(inputs) != expected:
            inputs = []
        snapshot = build_market_breadth(
            input_snapshot_id=input_snapshot.id,
            instruments=inputs,
            as_of_date=as_of,
        )
        persisted = uow.market_observation_snapshots.add(snapshot)
        uow.commit()
    return MarketBreadthPublishResult(
        snapshot=persisted,
        input_snapshot=input_snapshot,
        instrument_count=len(inputs),
    )


def calculate_and_publish_market_breadth_v2(
    *,
    uow_factory: UnitOfWorkFactory,
    input_snapshot: InputSnapshot,
    as_of: date,
) -> MarketBreadthPublishResult:
    """Calculate the v2 breadth snapshot for ``as_of`` and persist it.

    The v2 algorithm uses 250 normal bars to compute MA20 (last 20 closes),
    MA60 (last 60 closes), and determines is_new_high / is_new_low by
    comparing the latest bar's high/low against the 250-bar window's
    max high and min low.

    The service is a thin orchestration layer over the existing
    ``invest_domain.analytics.market_breadth.build_market_breadth_v2``
    builder and the pre-existing
    :class:`invest_storage.SqlAlchemyMarketObservationSnapshotRepository`
    write path — it never bypasses those contracts and never opens a
    new table or migration.

    Parameters
    ----------
    uow_factory:
        A callable that hands out a fresh :class:`UnitOfWork` for the
        breadth read path. The service only opens one UoW so the
        breadth computation sees a consistent slice of
        ``core.daily_bars``.
    input_snapshot:
        The stock :class:`InputSnapshot` previously persisted by the
        :func:`invest_pipeline.assets.stock_input_snapshot` asset. Its
        ``snapshot_date`` must equal ``as_of``; a mismatch is a
        configuration / partition-alignment error and is raised
        immediately.
    as_of:
        The business trade date for the breadth snapshot. The service
        derives the rolling 250-day window from this value and never
        falls back to ``date.today()``.

    Returns
    -------
    MarketBreadthPublishResult
        A value object carrying the freshly-persisted
        :class:`MarketObservationSnapshot`, the input snapshot that
        bound the universe, and the count of instruments that
        contributed valid breadth inputs.
    """

    if input_snapshot.snapshot_date != as_of:
        raise ValueError(
            f"as_of {as_of.isoformat()} does not match input_snapshot."
            f"snapshot_date {input_snapshot.snapshot_date.isoformat()}; "
            "the breadth service refuses to silently fall back to a "
            "different trade date"
        )

    with uow_factory() as uow:
        inputs: list[MarketBreadthInput] = []
        expected = len(input_snapshot.instrument_ids)
        for instrument_id in input_snapshot.instrument_ids:
            bars = _bars_in_window_v2(
                uow,
                instrument_id=instrument_id,
                end_date=as_of,
            )
            breadth_input = _select_breadth_input_v2(
                instrument_id=instrument_id,
                bars=bars,
                as_of=as_of,
            )
            if breadth_input is not None:
                inputs.append(breadth_input)
        if expected > 0 and len(inputs) != expected:
            inputs = []
        snapshot = build_market_breadth_v2(
            input_snapshot_id=input_snapshot.id,
            instruments=inputs,
            as_of_date=as_of,
        )
        persisted = uow.market_observation_snapshots.add(snapshot)
        uow.commit()
    return MarketBreadthPublishResult(
        snapshot=persisted,
        input_snapshot=input_snapshot,
        instrument_count=len(inputs),
    )
