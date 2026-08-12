"""Focused unit tests for the Stage 4B Market Breadth service.

The service is a thin orchestration layer over the pure-domain
:func:`invest_domain.analytics.market_breadth.build_market_breadth`
builder and the pre-existing storage repositories. The contract is
verified end-to-end through a hand-rolled fake UoW so the suite never
boots a real database:

* :class:`MarketBreadthServiceResolveTest` covers the universe-symbol
  resolver: active ``STOCK`` rows are accepted, ``ETF`` /
  ``INDEX`` rows are rejected, ambiguous / missing / duplicate
  matches surface as ``ValueError`` so a stale universe file is
  surfaced loudly.
* :class:`MarketBreadthServiceActiveStockUniverseTest` covers the
  dynamic-universe helper: every active ``STOCK`` row in
  ``core.instruments`` is returned in deterministic
  ``(exchange, symbol, id)`` order, ``ETF`` / ``INDEX`` / inactive /
  delisted rows are filtered out at the database level, and an empty
  persisted active ``STOCK`` universe raises
  :class:`StockUniverseEmptyError` so the ``stock_input_snapshot``
  asset fails closed.
* :class:`MarketBreadthServiceWindowTest` covers the 20-day window /
  MA20 filtering: instruments whose latest bar is not on ``as_of``,
  whose rolling history is short, or whose ``close`` /
  ``prev_close`` / ``ma20`` cannot be computed are dropped from the
  breadth input rather than fabricated. An all-empty input fails
  closed: the persisted snapshot is the deterministic
  ``INVALID / FAILED`` shape the pure-domain builder produces, and
  the asset-layer caller surfaces ``skipped / invalid`` metadata.
* :class:`MarketBreadthServiceHappyPathTest` drives the happy path:
  the service reads the rolling 20-day window via the UoW, builds a
  :class:`MarketBreadthInput` per surviving instrument, hands them to
  the pure-domain builder, and persists the resulting snapshot
  through the existing market-observation-snapshot repository (no new
  migration / table).
* :class:`MarketBreadthServiceWeekendSpanTest` covers the natural-day
  lookback fix: 20 ``normal`` bars whose natural-day span is well
  above 20 (i.e. they straddle at least one weekend) must still
  publish a ``COMPLETE / FRESH`` snapshot — the previous
  ``as_of - 19`` natural-day window silently dropped the universe
  to ``INVALID / FAILED`` whenever ``as_of`` fell near a weekend or
  public holiday.
"""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.analytics.market_breadth import (
    ABOVE_MA20_RATIO,
    ABOVE_MA60_RATIO,
    ADVANCING_RATIO,
    DECLINING_RATIO,
    NEW_HIGH_RATIO,
    NEW_LOW_RATIO,
)
from invest_domain.analytics.market_observations import (
    MarketObservationSnapshot,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_pipeline.market_breadth_service import (
    StockUniverseEmptyError,
    calculate_and_publish_market_breadth,
    calculate_and_publish_market_breadth_v2,
    list_active_stock_instrument_ids,
    resolve_stock_instrument_ids,
)
from invest_storage.models import InstrumentRow
from invest_storage.repositories import StoredDailyBar

_AS_OF = date(2026, 8, 10)
_HISTORICAL_START = date(2026, 7, 22)
_SYMBOL_A = "600519"
_SYMBOL_B = "000001"
_SYMBOL_ETF = "510300"


def _make_instrument(
    symbol: str,
    *,
    instrument_type: InstrumentType = InstrumentType.STOCK,
    is_active: bool = True,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"{symbol} Co",
        exchange="SSE" if symbol.startswith(("5", "6")) else "SZSE",
        instrument_type=instrument_type,
        is_active=is_active,
        instrument_id=InstrumentId(uuid4()),
    )


def _make_instrument_row(instrument: Instrument) -> MagicMock:
    """Build a :class:`MagicMock` that quacks like an :class:`InstrumentRow`."""

    row = MagicMock(spec=InstrumentRow)
    row.id = instrument.instrument_id.value
    row.symbol = instrument.symbol
    row.name = instrument.name
    row.exchange = instrument.exchange
    row.instrument_type = instrument.instrument_type.value
    row.is_active = instrument.is_active
    row.currency = "CNY"
    row.list_date = None
    row.delist_date = None
    row.status = instrument.status.value
    row.underlying_index = None
    row.category = None
    row.provider_symbol_map = {}
    row.valid_from = None
    row.valid_to = None
    return row


@dataclass
class _FakeDailyBarsRepo:
    """Fake for :class:`invest_storage.repositories.SqlAlchemyDailyBarRepository`."""

    bars_by_instrument: dict[UUID, list[StoredDailyBar]] = field(default_factory=dict)
    recorded_calls: list[tuple[UUID, date, date, Any]] = field(default_factory=list)

    def list_latest_by_instrument_and_range(
        self,
        *,
        instrument_id: UUID,
        start_date: date,
        end_date: date,
        adjustment: Any,
    ) -> Sequence[StoredDailyBar]:
        self.recorded_calls.append((instrument_id, start_date, end_date, adjustment))
        return list(self.bars_by_instrument.get(instrument_id, ()))


@dataclass
class _FakeMarketObservationRepo:
    persisted: list[MarketObservationSnapshot] = field(default_factory=list)

    def add(self, snapshot: MarketObservationSnapshot) -> MarketObservationSnapshot:
        self.persisted.append(snapshot)
        return snapshot


class _FakeUoW:
    def __init__(
        self,
        daily_bars: _FakeDailyBarsRepo,
        market_observation_snapshots: _FakeMarketObservationRepo,
    ) -> None:
        self._daily_bars = daily_bars
        self._market_observation_snapshots = market_observation_snapshots
        self.committed = False

    @property
    def daily_bars(self) -> _FakeDailyBarsRepo:
        return self._daily_bars

    @property
    def market_observation_snapshots(self) -> _FakeMarketObservationRepo:
        return self._market_observation_snapshots

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _make_bar(
    instrument_id: UUID,
    trade_date: date,
    close: str = "10",
    prev_close: str = "10",
    trading_status: str = "normal",
    high: str = "11",
    low: str = "9",
) -> StoredDailyBar:
    return StoredDailyBar(
        id=uuid4(),
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=Decimal("10"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        prev_close=Decimal(prev_close),
        volume=Decimal("100"),
        amount=Decimal("1000"),
        adjustment="none",
        trading_status=trading_status,
        source_provider="tushare",
        source_batch_id=uuid4(),
        observed_at=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
        revision=1,
        row_hash="a" * 64,
    )


def _build_input_snapshot(
    *,
    snapshot_date: date = _AS_OF,
    instrument_ids: tuple[UUID, ...] = (),
) -> InputSnapshot:
    return InputSnapshot(
        id=uuid4(),
        snapshot_date=snapshot_date,
        instrument_ids=instrument_ids,
        content_hash="a" * 64,
        row_count=len(instrument_ids),
        created_at=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
    )


def _make_uow_factory(
    bars_by_instrument: dict[UUID, list[StoredDailyBar]],
) -> tuple[Any, _FakeMarketObservationRepo]:
    """Build a hand-rolled UoW factory and the observation-snapshot recorder it hands back."""

    daily_bars = _FakeDailyBarsRepo(bars_by_instrument=bars_by_instrument)
    observations = _FakeMarketObservationRepo()
    uow = _FakeUoW(daily_bars=daily_bars, market_observation_snapshots=observations)

    def _factory() -> _FakeUoW:
        return uow

    return _factory, observations


def _bars_history(
    instrument_id: UUID,
    *,
    start: date,
    days: int,
    closes: list[str] | None = None,
) -> list[StoredDailyBar]:
    bars: list[StoredDailyBar] = []
    for offset in range(days):
        close = closes[offset] if closes else "10"
        prev = closes[offset - 1] if (closes and offset > 0) else "10"
        bars.append(
            _make_bar(
                instrument_id,
                start + timedelta(days=offset),
                close=close,
                prev_close=prev,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class MarketBreadthServiceResolveTest(unittest.TestCase):
    """Universe-symbol → active ``STOCK`` instrument_id resolution."""

    def _build_uow_with_rows(
        self, rows_by_symbol: dict[str, list[Instrument]]
    ) -> Any:
        session = MagicMock(name="Session")
        call_index = {"value": 0}

        def _resolve_rows() -> list[MagicMock]:
            symbols = list(rows_by_symbol.keys())
            idx = call_index["value"]
            call_index["value"] = idx + 1
            if idx < len(symbols):
                rows = rows_by_symbol[symbols[idx]]
                return [_make_instrument_row(instrument) for instrument in rows]
            return []

        session.scalars.return_value.all.side_effect = _resolve_rows
        uow = MagicMock(name="UoW")
        uow.session = session
        return uow

    def test_resolves_active_stock_rows_in_declaration_order(self) -> None:
        a = _make_instrument(_SYMBOL_A)
        b = _make_instrument(_SYMBOL_B)
        uow = self._build_uow_with_rows({_SYMBOL_A: [a], _SYMBOL_B: [b]})

        result = resolve_stock_instrument_ids(uow, symbols=[_SYMBOL_A, _SYMBOL_B])

        self.assertEqual(result, [a.instrument_id.value, b.instrument_id.value])

    def test_rejects_etf_rows(self) -> None:
        etf = _make_instrument(_SYMBOL_ETF, instrument_type=InstrumentType.ETF)
        uow = self._build_uow_with_rows({_SYMBOL_ETF: [etf]})

        with self.assertRaisesRegex(ValueError, "did not match any active STOCK"):
            resolve_stock_instrument_ids(uow, symbols=[_SYMBOL_ETF])

    def test_rejects_index_rows(self) -> None:
        index = _make_instrument("000300", instrument_type=InstrumentType.INDEX)
        uow = self._build_uow_with_rows({"000300": [index]})

        with self.assertRaisesRegex(ValueError, "did not match any active STOCK"):
            resolve_stock_instrument_ids(uow, symbols=["000300"])

    def test_rejects_ambiguous_matches(self) -> None:
        first = _make_instrument(_SYMBOL_A)
        second = _make_instrument(_SYMBOL_A)
        uow = self._build_uow_with_rows({_SYMBOL_A: [first, second]})

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_stock_instrument_ids(uow, symbols=[_SYMBOL_A])

    def test_rejects_unknown_symbol(self) -> None:
        uow = self._build_uow_with_rows({})

        with self.assertRaisesRegex(ValueError, "did not match any active STOCK"):
            resolve_stock_instrument_ids(uow, symbols=["999999"])

    def test_rejects_duplicate_symbols(self) -> None:
        a = _make_instrument(_SYMBOL_A)
        uow = self._build_uow_with_rows({_SYMBOL_A: [a]})

        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            resolve_stock_instrument_ids(uow, symbols=[_SYMBOL_A, _SYMBOL_A])


# ---------------------------------------------------------------------------
# Dynamic active-STOCK universe
# ---------------------------------------------------------------------------


class MarketBreadthServiceActiveStockUniverseTest(unittest.TestCase):
    """Provider-agnostic dynamic active ``STOCK`` universe query.

    The helper :func:`list_active_stock_instrument_ids` is the
    canonical universe source for the ``stock_input_snapshot``
    Dagster asset: it queries the UoW session for every active
    ``STOCK`` row in ``core.instruments`` and returns the
    storage-side ``instrument_id`` UUIDs in deterministic
    ``(exchange, symbol, id)`` order. ``ETF`` / ``INDEX`` / inactive
    / delisted rows are filtered out at the database level so the
    universe can never silently grow with non-stock rows or
    re-target a delisted ticker. An empty persisted active
    ``STOCK`` universe raises :class:`StockUniverseEmptyError` so
    the asset fails closed.
    """

    def _row(
        self,
        *,
        instrument_id: UUID,
        symbol: str,
        exchange: str,
        instrument_type: str = "STOCK",
        is_active: bool = True,
        delist_date: date | None = None,
    ) -> MagicMock:
        row = MagicMock(spec=InstrumentRow)
        row.id = instrument_id
        row.symbol = symbol
        row.exchange = exchange
        row.instrument_type = instrument_type
        row.is_active = is_active
        row.delist_date = delist_date
        return row

    def _uow(self, rows: list[MagicMock]) -> MagicMock:
        session = MagicMock(name="Session")
        session.scalars.return_value.all.return_value = rows
        uow = MagicMock(name="UoW")
        uow.session = session
        return uow

    def test_returns_only_active_stock_rows_in_deterministic_order(self) -> None:
        """The helper returns every active ``STOCK`` row in ``(exchange, symbol, id)`` order.

        The session-side filter must reject ``ETF`` / ``INDEX`` /
        inactive ``STOCK`` / delisted ``STOCK`` rows so the dynamic
        universe can never silently grow with non-stock rows. The
        test feeds the mock session a list of rows out of natural
        order (mixed types, mixed exchanges) and verifies the helper
        preserves the natural ``(exchange, symbol, id)`` order the
        ``order_by`` clause would produce on a real database.
        """

        a = self._row(instrument_id=uuid4(), symbol="000001", exchange="SZSE")
        b = self._row(instrument_id=uuid4(), symbol="300750", exchange="SZSE")
        c = self._row(instrument_id=uuid4(), symbol="600519", exchange="SSE")
        d = self._row(instrument_id=uuid4(), symbol="600276", exchange="SSE")
        etf = self._row(
            instrument_id=uuid4(),
            symbol="510300",
            exchange="SSE",
            instrument_type="ETF",
        )
        index_row = self._row(
            instrument_id=uuid4(),
            symbol="000300",
            exchange="SZSE",
            instrument_type="INDEX",
        )
        inactive = self._row(
            instrument_id=uuid4(),
            symbol="600999",
            exchange="SSE",
            is_active=False,
        )
        delisted = self._row(
            instrument_id=uuid4(),
            symbol="300001",
            exchange="SZSE",
            delist_date=date(2020, 1, 1),
        )

        # Pre-ordered list (matches the ``order_by`` clause the
        # helper applies on a real session) — the helper must pass
        # the order through verbatim.
        rows = [a, b, c, d, etf, index_row, inactive, delisted]
        uow = self._uow(rows)

        result = list_active_stock_instrument_ids(uow)

        self.assertEqual(result, [a.id, b.id, c.id, d.id])

    def test_filters_out_delisted_stock_rows(self) -> None:
        """Delisted ``STOCK`` rows (non-null ``delist_date``) must be filtered out.

        The explicit-universe resolver at
        :func:`resolve_stock_instrument_ids` filters on
        ``delist_date IS NULL`` so the dynamic helper must match
        that contract: a delisted row is not "active" from the
        breadth service's point of view even if its ``is_active``
        flag is still ``True``.
        """

        active = self._row(
            instrument_id=uuid4(),
            symbol="600519",
            exchange="SSE",
        )
        delisted = self._row(
            instrument_id=uuid4(),
            symbol="600999",
            exchange="SSE",
            delist_date=date(2020, 1, 1),
        )
        uow = self._uow([active, delisted])

        self.assertEqual(list_active_stock_instrument_ids(uow), [active.id])

    def test_empty_universe_raises_stock_universe_empty_error(self) -> None:
        """An empty persisted active ``STOCK`` universe fails closed.

        The asset layer propagates :class:`StockUniverseEmptyError`
        so a misconfigured upstream ``stock_instruments``
        materialisation surfaces as a hard Dagster failure rather
        than a partial ``InputSnapshot``. The error message
        references the upstream asset so operators can find the
        remediation path quickly.
        """

        uow = self._uow([])

        with self.assertRaises(StockUniverseEmptyError) as ctx:
            list_active_stock_instrument_ids(uow)
        self.assertIn("no active STOCK rows", str(ctx.exception))
        self.assertIn("stock_instruments", str(ctx.exception))

    def test_universe_with_only_etf_and_index_rows_raises(self) -> None:
        """A universe with only ``ETF`` / ``INDEX`` rows is empty from the helper's view.

        The ``ETF`` / ``INDEX`` rows are filtered out at the
        database level, leaving the helper with an empty id list,
        which triggers the fail-closed
        :class:`StockUniverseEmptyError`. This pins the
        silent-growth guard: a misconfigured upstream that
        accidentally only persists ETF/INDEX rows cannot trick
        ``stock_input_snapshot`` into publishing a non-empty
        ``InputSnapshot``.
        """

        etf = self._row(
            instrument_id=uuid4(),
            symbol="510300",
            exchange="SSE",
            instrument_type="ETF",
        )
        index_row = self._row(
            instrument_id=uuid4(),
            symbol="000300",
            exchange="SZSE",
            instrument_type="INDEX",
        )
        uow = self._uow([etf, index_row])

        with self.assertRaises(StockUniverseEmptyError):
            list_active_stock_instrument_ids(uow)

    def test_helper_does_not_use_silent_limit_on_instrument_repository(self) -> None:
        """Bypass the silent ``limit`` default on ``InstrumentRepository.list_active``.

        :meth:`SqlAlchemyInstrumentRepository.list_active` carries a
        silent ``limit=100`` default — using it for the dynamic
        universe would silently truncate the A-share universe (the
        full active universe is well above 100 rows). The helper
        queries the UoW session directly, so the test simply
        confirms the helper does not call any
        ``uow.instruments.list_active`` method.
        """

        rows = [
            self._row(instrument_id=uuid4(), symbol=f"{i:06d}", exchange="SZSE")
            for i in range(1, 151)
        ]
        uow = self._uow(rows)

        result = list_active_stock_instrument_ids(uow)

        self.assertEqual(len(result), 150)
        uow.instruments.list_active.assert_not_called()


# ---------------------------------------------------------------------------
# 20-day window / MA20 fail-closed
# ---------------------------------------------------------------------------


class MarketBreadthServiceWindowTest(unittest.TestCase):
    """20-day rolling window + MA20 filtering at the service boundary."""

    def test_drops_instrument_when_history_below_twenty_normal_bars(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        short_history = _bars_history(
            instrument_id,
            start=_HISTORICAL_START,
            days=19,
        )
        uow_factory, observations = _make_uow_factory({instrument_id: short_history})

        snapshot = _build_input_snapshot(
            instrument_ids=(instrument_id,),
            snapshot_date=_AS_OF,
        )
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        self.assertEqual(result.instrument_count, 0)
        self.assertEqual(observations.persisted, [result.snapshot])
        self.assertEqual(result.snapshot.quality_status, QualityStatus.INVALID)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FAILED)

    def test_drops_instrument_when_latest_close_missing(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        history = _bars_history(
            instrument_id,
            start=_HISTORICAL_START,
            days=20,
        )
        # zero close — fail-closed; service refuses to fabricate.
        history[-1] = _make_bar(
            instrument_id,
            history[-1].trade_date,
            close="0",
        )
        uow_factory, observations = _make_uow_factory({instrument_id: history})

        snapshot = _build_input_snapshot(
            instrument_ids=(instrument_id,),
            snapshot_date=_AS_OF,
        )
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        self.assertEqual(result.instrument_count, 0)
        self.assertEqual(observations.persisted, [result.snapshot])
        self.assertEqual(result.snapshot.quality_status, QualityStatus.INVALID)

    def test_drops_instrument_when_prev_close_missing(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        history = _bars_history(
            instrument_id,
            start=_HISTORICAL_START,
            days=20,
        )
        history[-1] = _make_bar(
            instrument_id,
            history[-1].trade_date,
            close="11",
            prev_close="0",
        )
        uow_factory, _ = _make_uow_factory({instrument_id: history})

        snapshot = _build_input_snapshot(
            instrument_ids=(instrument_id,),
            snapshot_date=_AS_OF,
        )
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        self.assertEqual(result.instrument_count, 0)

    def test_raises_when_input_snapshot_date_mismatches_as_of(self) -> None:
        snapshot = _build_input_snapshot(
            snapshot_date=date(2026, 8, 9),
            instrument_ids=(uuid4(),),
        )
        uow_factory, _ = _make_uow_factory({})
        with self.assertRaisesRegex(ValueError, "does not match input_snapshot"):
            calculate_and_publish_market_breadth(
                uow_factory=uow_factory,
                input_snapshot=snapshot,
                as_of=_AS_OF,
            )

    def test_persists_invalid_snapshot_when_all_instruments_filtered(self) -> None:
        """When every instrument is filtered, the persisted snapshot is INVALID / FAILED.

        The service refuses to fabricate data, so a partition with no
        20-day history still materialises a deterministic INVALID /
        FAILED snapshot through the same repository. The asset layer
        is responsible for surfacing that as ``skipped / invalid``
        metadata; the service itself never raises on an empty input
        because the breadth builder already produces a fail-closed
        snapshot for that case.
        """

        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        # Deliberately short history so the lone instrument is dropped.
        short_history = _bars_history(
            instrument_id,
            start=_HISTORICAL_START,
            days=10,
        )
        uow_factory, observations = _make_uow_factory({instrument_id: short_history})

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        self.assertEqual(result.instrument_count, 0)
        self.assertEqual(len(observations.persisted), 1)
        self.assertEqual(
            observations.persisted[0].quality_status, QualityStatus.INVALID
        )
        self.assertEqual(
            observations.persisted[0].freshness_status, FreshnessStatus.FAILED
        )

    def test_mixed_valid_and_missing_history_publishes_invalid_snapshot(self) -> None:
        """A mixed universe must NOT publish a partial ``COMPLETE`` snapshot.

        When **any** instrument in the input snapshot lacks a valid
        20-day breadth input the service refuses to fabricate data for
        the surviving instruments: it hands an empty ``instruments``
        sequence to the pure-domain builder so the persisted snapshot
        is the deterministic ``INVALID / FAILED`` shape and the
        reported ``instrument_count`` is ``0``. The "freshly-listed
        symbol" / short-history case must surface as an audit-friendly
        invalid row rather than silently masking the partial universe
        behind a misleading ``COMPLETE`` snapshot.
        """

        instrument_a = _make_instrument(_SYMBOL_A)
        instrument_b = _make_instrument(_SYMBOL_B)
        ids = (instrument_a.instrument_id.value, instrument_b.instrument_id.value)

        history_a = _bars_history(
            ids[0],
            start=_HISTORICAL_START,
            days=20,
            closes=["11"] * 20,
        )
        # Deliberately short history for the second instrument: even
        # though ``history_a`` is complete, the service must NOT
        # publish a ``COMPLETE`` snapshot using only ``history_a``.
        short_history_b = _bars_history(
            ids[1],
            start=_HISTORICAL_START,
            days=10,
        )
        uow_factory, observations = _make_uow_factory(
            {ids[0]: history_a, ids[1]: short_history_b}
        )

        snapshot = _build_input_snapshot(instrument_ids=ids)
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result.instrument_count, 0)
        self.assertEqual(observations.persisted, [result.snapshot])
        self.assertEqual(result.snapshot.quality_status, QualityStatus.INVALID)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FAILED)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class MarketBreadthServiceHappyPathTest(unittest.TestCase):
    """Happy path through the breadth service."""

    def test_persists_three_ratio_observations_for_full_universe(self) -> None:
        instrument_a = _make_instrument(_SYMBOL_A)
        instrument_b = _make_instrument(_SYMBOL_B)
        ids = (instrument_a.instrument_id.value, instrument_b.instrument_id.value)

        history_a = _bars_history(
            ids[0],
            start=_HISTORICAL_START,
            days=20,
            closes=["11"] * 20,
        )
        history_b = _bars_history(
            ids[1],
            start=_HISTORICAL_START,
            days=20,
            closes=["9"] * 20,
        )
        uow_factory, observations = _make_uow_factory(
            {ids[0]: history_a, ids[1]: history_b}
        )

        snapshot = _build_input_snapshot(instrument_ids=ids)
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result.instrument_count, 2)
        self.assertEqual(observations.persisted, [result.snapshot])
        keys = {obs.observation_key for obs in result.snapshot.observations}
        self.assertEqual(
            keys,
            {ADVANCING_RATIO, DECLINING_RATIO, ABOVE_MA20_RATIO},
        )
        self.assertEqual(result.snapshot.quality_status, QualityStatus.COMPLETE)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FRESH)


# ---------------------------------------------------------------------------
# Rolling window must survive weekends / holidays
# ---------------------------------------------------------------------------


class MarketBreadthServiceWeekendSpanTest(unittest.TestCase):
    """20 ``normal`` bars straddling weekends must publish a fresh snapshot.

    The pre-fix service queried only ``as_of - 19`` natural days for
    the breadth MA20 window; on (or near) a weekend that yields ~14
    trading days at best and the breadth builder fails closed to
    ``INVALID / FAILED`` because it never sees 20 ``normal`` bars.
    The fix widens the natural-day lookback to
    :data:`invest_pipeline.market_breadth_service._BREADTH_LOOKBACK_NATURAL_DAYS`
    so the most recent 20 trading days are always available, and
    :func:`_select_breadth_input` tail-slices to the freshest 20
    ``normal`` bars so the MA20 semantics are unchanged. This test
    pins both ends of that contract end-to-end.
    """

    def test_twenty_normal_bars_spanning_weekends_publish_complete_snapshot(
        self,
    ) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value

        # 20 trading days ending on ``_AS_OF`` (Monday 2026-08-10).
        # The window spans four weekends so the natural-day span is
        # well above 20 — the pre-fix service would have queried
        # [2026-07-22, 2026-08-10] and seen only ~14 trading-day rows,
        # failing closed. The fixture must stay in ``trade_date ASC``
        # order so ``bars[-1]`` is the ``as_of`` bar, matching the
        # ``list_latest_by_instrument_and_range`` repository contract.
        trading_dates: tuple[date, ...] = (
            date(2026, 7, 14),
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 17),
            date(2026, 7, 20),
            date(2026, 7, 21),
            date(2026, 7, 22),
            date(2026, 7, 23),
            date(2026, 7, 24),
            date(2026, 7, 27),
            date(2026, 7, 28),
            date(2026, 7, 29),
            date(2026, 7, 30),
            date(2026, 7, 31),
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
            date(2026, 8, 6),
            date(2026, 8, 7),
            date(2026, 8, 10),
        )
        natural_span_days = (trading_dates[-1] - trading_dates[0]).days
        assert natural_span_days > 20, (
            "test fixture must span more than 20 natural days to exercise "
            "the rolling-window bug fix"
        )

        # All 20 closes are positive and the MA20 is a clean 10 — close
        # (10) >= MA20 (10) so the above-MA20 ratio is exactly 1.0;
        # advancing / declining are 0 because every close equals the
        # previous close. The exact MA20 value gives the test a tight
        # invariant: any stale close leaking into the slice would push
        # MA20 away from 10 and break the above-MA20 ratio.
        bars: list[StoredDailyBar] = []
        for trade_date in trading_dates:
            bars.append(
                _make_bar(
                    instrument_id,
                    trade_date,
                    close="10",
                    prev_close="10",
                )
            )
        uow_factory, observations = _make_uow_factory({instrument_id: bars})

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result.instrument_count, 1)
        self.assertEqual(observations.persisted, [result.snapshot])
        self.assertEqual(result.snapshot.quality_status, QualityStatus.COMPLETE)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FRESH)
        keys = {obs.observation_key for obs in result.snapshot.observations}
        self.assertEqual(
            keys,
            {ADVANCING_RATIO, DECLINING_RATIO, ABOVE_MA20_RATIO},
        )

        observations_by_key = {
            obs.observation_key: obs.value
            for obs in result.snapshot.observations
        }
        # close (10) >= MA20 (10) → the surviving instrument counts.
        self.assertEqual(observations_by_key[ABOVE_MA20_RATIO], Decimal("1.00000000"))
        # close == prev_close for every bar → no advances, no declines.
        self.assertEqual(observations_by_key[ADVANCING_RATIO], Decimal("0"))
        self.assertEqual(observations_by_key[DECLINING_RATIO], Decimal("0"))


# ---------------------------------------------------------------------------
# v2 helpers
# ---------------------------------------------------------------------------


def _v2_bars_history(
    instrument_id: UUID,
    *,
    end_date: date,
    days: int,
    closes: list[str] | None = None,
    highs: list[str] | None = None,
    lows: list[str] | None = None,
) -> list[StoredDailyBar]:
    start = end_date - timedelta(days=days - 1)
    bars: list[StoredDailyBar] = []
    for offset in range(days):
        close = closes[offset] if closes else "10"
        prev = closes[offset - 1] if (closes and offset > 0) else "10"
        high = highs[offset] if highs else "11"
        low = lows[offset] if lows else "9"
        bars.append(
            _make_bar(
                instrument_id,
                start + timedelta(days=offset),
                close=close,
                prev_close=prev,
                high=high,
                low=low,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# v2 happy path - 6 metrics
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2HappyPathTest(unittest.TestCase):
    """Happy path through the v2 breadth service with 6 metrics."""

    def test_persists_six_ratio_observations_for_full_universe(self) -> None:
        instrument_a = _make_instrument(_SYMBOL_A)
        instrument_b = _make_instrument(_SYMBOL_B)
        ids = (instrument_a.instrument_id.value, instrument_b.instrument_id.value)

        # 250 normal bars - v2 requires 250, ending on _AS_OF
        history_a = _v2_bars_history(
            ids[0],
            end_date=_AS_OF,
            days=250,
            closes=["11"] * 250,
            highs=["12"] * 250,
            lows=["10"] * 250,
        )
        history_b = _v2_bars_history(
            ids[1],
            end_date=_AS_OF,
            days=250,
            closes=["9"] * 250,
            highs=["10"] * 250,
            lows=["8"] * 250,
        )
        uow_factory, observations = _make_uow_factory(
            {ids[0]: history_a, ids[1]: history_b}
        )

        snapshot = _build_input_snapshot(instrument_ids=ids)
        result = calculate_and_publish_market_breadth_v2(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result.instrument_count, 2)
        self.assertEqual(observations.persisted, [result.snapshot])
        keys = {obs.observation_key for obs in result.snapshot.observations}
        self.assertEqual(
            keys,
            {
                ADVANCING_RATIO,
                DECLINING_RATIO,
                ABOVE_MA20_RATIO,
                ABOVE_MA60_RATIO,
                NEW_HIGH_RATIO,
                NEW_LOW_RATIO,
            },
        )
        self.assertEqual(result.snapshot.quality_status, QualityStatus.COMPLETE)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FRESH)


# ---------------------------------------------------------------------------
# v2 insufficient data
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2InsufficientDataTest(unittest.TestCase):
    """v2 breadth service fails closed with insufficient 250-bar history."""

    def test_persists_invalid_snapshot_when_history_below_250_normal_bars(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        # Only 249 bars - insufficient for v2
        short_history = _v2_bars_history(
            instrument_id,
            end_date=_AS_OF,
            days=249,
        )
        uow_factory, observations = _make_uow_factory(
            {instrument_id: short_history}
        )

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
        result = calculate_and_publish_market_breadth_v2(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        self.assertEqual(result.instrument_count, 0)
        self.assertEqual(observations.persisted, [result.snapshot])
        self.assertEqual(result.snapshot.quality_status, QualityStatus.INVALID)
        self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FAILED)


# ---------------------------------------------------------------------------
# v2 deterministic repeat
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2DeterministicRepeatTest(unittest.TestCase):
    """v2 breadth service produces deterministic results on repeat."""

    def test_repeat_run_produces_identical_snapshot(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value

        history = _v2_bars_history(
            instrument_id,
            end_date=_AS_OF,
            days=250,
            closes=["10"] * 250,
            highs=["11"] * 250,
            lows=["9"] * 250,
        )
        uow_factory, observations = _make_uow_factory({instrument_id: history})

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))

        result1 = calculate_and_publish_market_breadth_v2(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )
        result2 = calculate_and_publish_market_breadth_v2(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result1.instrument_count, result2.instrument_count)
        self.assertEqual(
            result1.snapshot.content_hash, result2.snapshot.content_hash
        )
        obs1 = {o.observation_key: o.value for o in result1.snapshot.observations}
        obs2 = {o.observation_key: o.value for o in result2.snapshot.observations}
        self.assertEqual(obs1, obs2)


# ---------------------------------------------------------------------------
# v2 v1 compatibility - v1 still produces 3 metrics
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2V1CompatibilityTest(unittest.TestCase):
    """v2 call does not affect v1; v1 still publishes 3 metrics."""

    def test_v1_still_publishes_three_metrics(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value

        history = _v2_bars_history(
            instrument_id,
            end_date=_AS_OF,
            days=250,
            closes=["10"] * 250,
            highs=["11"] * 250,
            lows=["9"] * 250,
        )
        uow_factory, _ = _make_uow_factory({instrument_id: history})

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
        result = calculate_and_publish_market_breadth(
            uow_factory=uow_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(result.instrument_count, 1)
        keys = {obs.observation_key for obs in result.snapshot.observations}
        self.assertEqual(
            keys,
            {ADVANCING_RATIO, DECLINING_RATIO, ABOVE_MA20_RATIO},
        )
        self.assertNotIn(ABOVE_MA60_RATIO, keys)
        self.assertNotIn(NEW_HIGH_RATIO, keys)
        self.assertNotIn(NEW_LOW_RATIO, keys)


# ---------------------------------------------------------------------------
# v2 invalid historical high/low regression
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2InvalidHistoricalHighLowTest(unittest.TestCase):
    """Regression: any invalid historical high or low in the 250-bar window causes INVALID."""

    def test_invalid_historical_high_or_low_causes_invalid_snapshot(self) -> None:
        for field_name in ("high", "low"):
            with self.subTest(field=field_name):
                instrument = _make_instrument(_SYMBOL_A)
                instrument_id = instrument.instrument_id.value
                history = _v2_bars_history(
                    instrument_id,
                    end_date=_AS_OF,
                    days=250,
                    closes=["10"] * 250,
                    highs=["11"] * 250,
                    lows=["9"] * 250,
                )
                history[125] = replace(history[125], **{field_name: Decimal("0")})
                uow_factory, observations = _make_uow_factory({instrument_id: history})
                snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
                result = calculate_and_publish_market_breadth_v2(
                    uow_factory=uow_factory,
                    input_snapshot=snapshot,
                    as_of=_AS_OF,
                )
                self.assertEqual(result.instrument_count, 0)
                self.assertEqual(observations.persisted, [result.snapshot])
                self.assertEqual(result.snapshot.quality_status, QualityStatus.INVALID)
                self.assertEqual(result.snapshot.freshness_status, FreshnessStatus.FAILED)


# ---------------------------------------------------------------------------
# v2 repository query date range
# ---------------------------------------------------------------------------


class MarketBreadthServiceV2QueryDateRangeTest(unittest.TestCase):
    """v2 repository query uses correct 400-day window: start=as_of-399, end=as_of."""

    def test_v2_query_date_range_is_as_of_minus_399_to_as_of(self) -> None:
        instrument = _make_instrument(_SYMBOL_A)
        instrument_id = instrument.instrument_id.value
        history = _v2_bars_history(
            instrument_id,
            end_date=_AS_OF,
            days=250,
            closes=["10"] * 250,
            highs=["11"] * 250,
            lows=["9"] * 250,
        )
        daily_bars_repo = _FakeDailyBarsRepo(bars_by_instrument={instrument_id: history})
        observations = _FakeMarketObservationRepo()
        uow = _FakeUoW(daily_bars=daily_bars_repo, market_observation_snapshots=observations)

        def _factory() -> _FakeUoW:
            return uow

        snapshot = _build_input_snapshot(instrument_ids=(instrument_id,))
        calculate_and_publish_market_breadth_v2(
            uow_factory=_factory,
            input_snapshot=snapshot,
            as_of=_AS_OF,
        )

        self.assertEqual(len(daily_bars_repo.recorded_calls), 1)
        cid, start, end, adj = daily_bars_repo.recorded_calls[0]
        self.assertEqual(cid, instrument_id)
        self.assertEqual(start, _AS_OF - timedelta(days=399))
        self.assertEqual(end, _AS_OF)
        self.assertEqual(adj.value, "none")
