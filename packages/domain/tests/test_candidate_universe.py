from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from invest_domain.candidate_pool.universe import UniverseEligibility, build_etf_universe
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus


def _iid(n: int) -> InstrumentId:
    return InstrumentId(UUID(f"00000000-0000-4000-8000-{n:012d}"))


def _bar(iid, day, revision=1, close="3.15", status=TradingStatus.NORMAL):
    return DailyBar.build(instrument_id=iid, trade_date=day, open=Decimal(close) if status is TradingStatus.NORMAL else None, high=Decimal(close) if status is TradingStatus.NORMAL else None, low=Decimal(close) if status is TradingStatus.NORMAL else None, close=Decimal(close) if status is TradingStatus.NORMAL else None, prev_close=Decimal(close) if status is TradingStatus.NORMAL else None, volume=Decimal("1") if status is TradingStatus.NORMAL else None, amount=Decimal("1") if status is TradingStatus.NORMAL else None, adjustment=Adjust.NONE, trading_status=status, source=BarSource("test", UUID("00000000-0000-4000-8000-000000000999"), __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)), revision=revision)


def _instrument(iid, *, kind=InstrumentType.ETF, exchange="SSE", active=True):
    return Instrument("510300", "ETF", exchange, kind, is_active=active, instrument_id=iid)


def test_history_boundaries_and_dynamic_count():
    as_of = date(2026, 7, 30)
    instruments = [_instrument(_iid(i)) for i in range(1, 5)]
    bars = {_iid(i): [_bar(_iid(i), as_of - timedelta(days=day)) for day in range(1, count + 1)] for i, count in enumerate((7, 20, 59, 60), 1)}
    result = build_etf_universe(instruments, bars, as_of, max_stale_days=100)
    assert [item.history_days for item in result] == [7, 20, 59, 60]
    assert [item.eligibility for item in result] == [UniverseEligibility.INELIGIBLE, UniverseEligibility.PARTIAL, UniverseEligibility.PARTIAL, UniverseEligibility.FULL]


def test_future_stale_suspended_and_ineligible_reasons():
    as_of = date(2026, 7, 30)
    iid = _iid(10)
    item = build_etf_universe([_instrument(iid)], {iid: [_bar(iid, date(2026, 7, 29)), _bar(iid, date(2026, 8, 1)), _bar(iid, date(2026, 7, 28), status=TradingStatus.SUSPENDED)]}, as_of)[0]
    assert item.eligibility is UniverseEligibility.INELIGIBLE
    assert {"future_bar", "suspended", "insufficient_history"}.issubset(item.reasons)


def test_non_etf_non_exchange_and_inactive_are_ineligible():
    as_of = date(2026, 7, 30)
    for instrument in (_instrument(_iid(11), kind=InstrumentType.STOCK), _instrument(_iid(12), exchange="SSE", active=False)):
        item = build_etf_universe([instrument], {}, as_of)[0]
        assert item.eligibility is UniverseEligibility.INELIGIBLE


def test_order_independent_revision_conflict():
    as_of = date(2026, 7, 30)
    iid = _iid(20)
    bars = [_bar(iid, date(2026, 7, 30), revision=1, close="3.15"), _bar(iid, date(2026, 7, 30), revision=2, close="3.16")]
    assert build_etf_universe([_instrument(iid)], {iid: bars}, as_of) == build_etf_universe([_instrument(iid)], {iid: list(reversed(bars))}, as_of)
