"""Tests for the stock daily-bars ETL service.

- ``write_stock_daily_bars_raw`` writes a JSONB sidecar carrying both
  ``symbol`` and ``exchange`` per record (driven by the provider's
  ``symbol_and_exchange_for_instrument_id`` reverse lookup, not by
  symbol-prefix inference) and persists a fresh attempt on each rerun.
- ``upsert_stock_daily_bars`` reads the LATEST succeeded attempt for the
  logical key and resolves ``core.instruments.id`` via
  ``(symbol, exchange)`` from the sidecar.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttemptStatus,
    ProviderBatchStatus,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.stock_daily_bars import (
    serialize_stock_daily_bars,
    upsert_stock_daily_bars,
    write_stock_daily_bars_raw,
    write_stock_daily_bars_raw_by_trade_date,
)
from invest_storage.models import ProviderAttemptRow, ProviderRequestRow
from invest_storage.repositories import (
    NewProviderRequest,
    SqlAlchemyDailyBarRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session

_FIXED_OBSERVED_AT = datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC)


class _FakeUnitOfWork:
    """Write-path UoW stub: captures ``session.add`` and shares one request log across UoWs."""

    def __init__(self, session: MagicMock, *, request_log: list[ProviderRequestRow]) -> None:
        self._session = session
        self._request_log = request_log
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)

    def _get_or_create(self, request: NewProviderRequest) -> StoredProviderRequest:
        for row in self._request_log:
            if (
                row.provider_key == request.provider_key
                and row.dataset_key == request.dataset_key
                and row.request_key == request.request_key
            ):
                return _stored_request(row)
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
        return _stored_request(new_row)

    def _list_by_request(
        self, request_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[StoredProviderAttempt]:
        matched = sorted(
            (
                r
                for r in self._session.added_rows
                if isinstance(r, ProviderAttemptRow) and r.provider_request_id == request_id
            ),
            key=lambda r: r.attempt_no,
        )
        return [
            StoredProviderAttempt(
                id=r.id,
                provider_request_id=r.provider_request_id,
                attempt_no=r.attempt_no,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                error_stage=r.error_stage,
                error_code=r.error_code,
                error_message=r.error_message,
                response_payload_sha256=r.response_payload_sha256,
                response_payload_json=r.response_payload_json,
            )
            for r in matched[offset : offset + limit]
        ]

    provider_requests = property(lambda self: self._provider_requests)
    provider_attempts = property(lambda self: self._provider_attempts)
    provider_batches = property(lambda self: self._provider_batches)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(self, exc_type, exc, tb):
        (self.rollback() if exc_type is not None else self.commit())
        self._session.close()


class _UpsertFakeUnitOfWork:
    """Read-path UoW stub: pins the four read methods and captures upsert_many calls."""

    def __init__(
        self,
        session: MagicMock,
        *,
        stored_request: StoredProviderRequest | None,
        attempts: list[StoredProviderAttempt],
        instrument_lookup: Any,
        upsert_calls: list[list[Any]],
    ) -> None:
        self._session = session
        self._upsert_calls = upsert_calls
        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._daily_bars = SqlAlchemyDailyBarRepository(session)
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_by_logical_key = MagicMock(  # type: ignore[method-assign]
            return_value=stored_request,
        )
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = MagicMock(  # type: ignore[method-assign]
            return_value=list(attempts),
        )
        self._instruments.get_by_business_key = MagicMock(  # type: ignore[method-assign]
            side_effect=instrument_lookup,
        )
        self._daily_bars.upsert_many = MagicMock(  # type: ignore[method-assign]
            side_effect=self._record_upsert_call,
        )

    def _record_upsert_call(self, bars: Any) -> list[Any]:
        snapshot = list(bars)
        self._upsert_calls.append(snapshot)
        return snapshot

    provider_requests = property(lambda self: self._provider_requests)
    provider_attempts = property(lambda self: self._provider_attempts)
    instruments = property(lambda self: self._instruments)
    daily_bars = property(lambda self: self._daily_bars)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _UpsertFakeUnitOfWork:
        return self

    def __exit__(self, exc_type, exc, tb):
        (self.rollback() if exc_type is not None else self.commit())
        self._session.close()


def _stored_request(row: ProviderRequestRow) -> StoredProviderRequest:
    return StoredProviderRequest(
        id=row.id,
        provider_key=row.provider_key,
        dataset_key=row.dataset_key,
        request_key=row.request_key,
        request_params=dict(row.request_params or {}),
        requested_by_run_id=row.requested_by_run_id,
        status=row.status,
    )


def _build_session() -> MagicMock:
    """Return a ``MagicMock(spec=Session)`` recording ``add`` and resolving ``session.get``."""
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


def _make_uow_factory(session: MagicMock, *, uow_cls: type, **kwargs: Any) -> MagicMock:
    """Return a UoW factory that hands out ``uow_cls(session, **kwargs)`` on every call."""

    def _factory(*_a: Any, **_k: Any) -> Any:
        return uow_cls(session, **kwargs)

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _attempt_payload(session: MagicMock) -> dict[str, Any]:
    rows = [r for r in session.added_rows if isinstance(r, ProviderAttemptRow)]
    assert len(rows) == 1, f"exactly one attempt row, got {len(rows)}"
    payload = rows[0].response_payload_json
    assert payload is not None, "attempt must carry the sidecar"
    return json.loads(str(payload))


def _batch_rows(session: MagicMock) -> list[Any]:
    return [r for r in session.added_rows if type(r).__name__ == "RawProviderBatchRow"]


def _build_daily_bar(
    *,
    instrument_id: InstrumentId,
    trade_date: date,
    close: Decimal,
    attempt_id: UUID,
    observed_at: datetime,
) -> DailyBar:
    return DailyBar.build(
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=close,
        high=close + Decimal("0.02"),
        low=close - Decimal("0.02"),
        close=close,
        prev_close=close - Decimal("0.01"),
        volume=Decimal("1000"),
        amount=Decimal("1000000"),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=BarSource(
            provider_key="tushare", source_batch_id=attempt_id, observed_at=observed_at
        ),
        revision=1,
    )


def _build_provider_response(
    *,
    symbols: list[str],
    start_date: date,
    end_date: date,
    attempt_id: UUID,
    status: ProviderAttemptStatus = ProviderAttemptStatus.SUCCEEDED,
    records: tuple[DailyBar, ...] = (),
    error_stage: Any = None,
    error_code: str | None = None,
    error_message: str | None = None,
    warnings: tuple[str, ...] = (),
) -> tuple[Any, Any, Any]:
    iso_range = f"{start_date.isoformat()}-{end_date.isoformat()}"
    request = MagicMock(
        name="ProviderRequest",
        provider_key="tushare",
        dataset_key="stock_daily_bars",
        request_key=f"daily-bars-{iso_range}-{'-'.join(symbols)}",
        params={
            "symbols": list(symbols),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    attempt = MagicMock(
        name="ProviderAttempt",
        attempt_number=1,
        status=status,
        started_at=_FIXED_OBSERVED_AT,
        finished_at=_FIXED_OBSERVED_AT,
        error_stage=error_stage,
        error_code=error_code,
        error_message=error_message,
    )
    if status is ProviderAttemptStatus.FAILED:
        return request, attempt, None
    batch = MagicMock(
        name="ProviderBatch",
        attempt_id=attempt_id,
        records=records,
        raw_payload_hash="0" * 64,
        status=ProviderBatchStatus.SUCCEEDED,
        warnings=warnings,
    )
    return request, attempt, batch


class _TushareStyleStubProvider:
    """Provider stub standing in for ``StockTushareProvider``.

    Mirrors the ``symbol_and_exchange_for_instrument_id`` reverse
    lookup contract the real Tushare adapter exposes; keeps a private
    placeholder cache keyed by ``(symbol, exchange)``.
    """

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], InstrumentId] = {}
        self._records_by_symbol: dict[str, list[tuple[date, Decimal]]] = {}

    def register(self, symbol: str, exchange: str, bars: list[tuple[date, Decimal]]) -> None:
        """Pre-populate the placeholder table keyed by ``(symbol, exchange)`` and the bar plan."""
        self._ids[(symbol, exchange)] = InstrumentId.generate()
        self._records_by_symbol[symbol] = (exchange, list(bars))

    @property
    def provider_key(self) -> str:
        return "tushare"

    def fetch_daily_bars(
        self, symbols: list[str], start_date: date, end_date: date
    ) -> tuple[Any, Any, Any]:
        if not symbols:
            raise ValueError("symbols must not be empty")
        attempt_id = uuid4()
        observed = datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC)
        records: list[DailyBar] = []
        warnings: list[str] = []
        for symbol in symbols:
            schedule = self._records_by_symbol.get(symbol)
            if schedule is None:
                warnings.append(f"no schedule registered for {symbol}")
                continue
            exchange, bars = schedule
            placeholder = self._ids.get((symbol, exchange))
            if placeholder is None:
                warnings.append(f"no placeholder for {symbol}/{exchange}")
                continue
            records.extend(
                _build_daily_bar(
                    instrument_id=placeholder,
                    trade_date=trade_date,
                    close=close,
                    attempt_id=attempt_id,
                    observed_at=observed,
                )
                for trade_date, close in bars
                if start_date <= trade_date <= end_date
            )
        return _build_provider_response(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            attempt_id=attempt_id,
            records=tuple(records),
            warnings=tuple(warnings),
        )

    def symbol_and_exchange_for_instrument_id(
        self,
        instrument_id: InstrumentId,
    ) -> tuple[str, str] | None:
        for (symbol, exchange), value in self._ids.items():
            if value == instrument_id:
                return symbol, exchange
        return None


class _InlineProvider:
    """Inline provider stub: ``fetch_daily_bars`` and the reverse lookup are caller-supplied."""

    def __init__(self, fetch: Any, *, reverse_lookup: Any = lambda _: None) -> None:
        self._fetch = fetch
        self._reverse_lookup = reverse_lookup

    @property
    def provider_key(self) -> str:
        return "tushare"

    def fetch_daily_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[Any, Any, Any]:
        return self._fetch(symbols, start_date, end_date)

    def symbol_and_exchange_for_instrument_id(
        self,
        instrument_id: Any,
    ) -> tuple[str, str] | None:
        return self._reverse_lookup(instrument_id)


class _ByTradeDateInlineProvider:
    """Provider stub for the by-trade-date path.

    Mirrors :meth:`StockTushareProvider.fetch_daily_bars_by_trade_date`
    — a single request keyed by ``trade_date`` — and the same reverse
    lookup the per-symbol path exposes. ``fetch_daily_bars`` is
    deliberately omitted; the by-trade-date port only requires
    ``fetch_daily_bars_by_trade_date`` plus the reverse lookup.
    """

    def __init__(self, fetch_by_trade_date: Any, *, reverse_lookup: Any = lambda _: None) -> None:
        self._fetch_by_trade_date = fetch_by_trade_date
        self._reverse_lookup = reverse_lookup

    @property
    def provider_key(self) -> str:
        return "tushare"

    def fetch_daily_bars_by_trade_date(
        self,
        trade_date: date,
    ) -> tuple[Any, Any, Any]:
        return self._fetch_by_trade_date(trade_date)

    def symbol_and_exchange_for_instrument_id(
        self,
        instrument_id: Any,
    ) -> tuple[str, str] | None:
        return self._reverse_lookup(instrument_id)


def _build_by_trade_date_response(
    *,
    trade_date: date,
    records: tuple[DailyBar, ...],
    attempt_id: UUID,
    status: ProviderAttemptStatus = ProviderAttemptStatus.SUCCEEDED,
    error_stage: Any = None,
    error_code: str | None = None,
    error_message: str | None = None,
    warnings: tuple[str, ...] = (),
) -> tuple[Any, Any, Any]:
    """Build a ``(request, attempt, batch)`` triple for the by-date provider stub."""

    request = MagicMock(
        name="ProviderRequest",
        provider_key="tushare",
        dataset_key="stock_daily_bars_by_date",
        request_key=f"daily-bars-by-date-{trade_date.isoformat()}",
        params={"trade_date": trade_date.isoformat()},
    )
    attempt = MagicMock(
        name="ProviderAttempt",
        attempt_number=1,
        status=status,
        started_at=_FIXED_OBSERVED_AT,
        finished_at=_FIXED_OBSERVED_AT,
        error_stage=error_stage,
        error_code=error_code,
        error_message=error_message,
    )
    if status is ProviderAttemptStatus.FAILED:
        return request, attempt, None
    batch = MagicMock(
        name="ProviderBatch",
        attempt_id=attempt_id,
        records=records,
        raw_payload_hash="0" * 64,
        status=ProviderBatchStatus.SUCCEEDED,
        warnings=warnings,
    )
    return request, attempt, batch


def _build_write_session() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return a ``(session, session_factory, uow_factory)`` triple for write-path tests."""
    session = _build_session()
    log: list[ProviderRequestRow] = []
    return (
        session,
        _make_session_factory(session),
        _make_uow_factory(session, uow_cls=_FakeUnitOfWork, request_log=log),
    )


class WriteStockDailyBarsRawSidecarTest(unittest.TestCase):
    """The sidecar must carry ``symbol`` and ``exchange`` per record."""

    def setUp(self) -> None:
        self._provider = _TushareStyleStubProvider()
        self._provider.register("600519", "SSE", [(date(2026, 7, 27), Decimal("1800.50"))])
        self._provider.register("000001", "SZSE", [(date(2026, 7, 27), Decimal("10.50"))])
        self._start = date(2026, 7, 27)
        self._end = date(2026, 7, 27)
        self._session, self._factory, self._uow_factory = _build_write_session()

    def test_sidecar_records_carry_symbol_and_exchange(self) -> None:
        result = write_stock_daily_bars_raw(
            self._provider,
            self._factory,
            symbols=["600519", "000001"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(result.record_count, 2)
        parsed = _attempt_payload(self._session)
        records = parsed["records"]
        self.assertEqual(len(records), 2)

        seen = {(e["symbol"], e["exchange"]) for e in records}
        self.assertEqual(seen, {("600519", "SSE"), ("000001", "SZSE")})

        # ``source_provider`` is the audit field, independent of the ``exchange`` slot.
        self.assertEqual({e["source_provider"] for e in records}, {"tushare"})

    def test_exchange_comes_from_provider_not_from_prefix(self) -> None:
        # 0-prefix symbol registered as ``"SSE"`` must surface as ``("000001", "SSE")`` —
        # prefix-guessing would coerce to ``("000001", "SZSE")``.
        provider = _TushareStyleStubProvider()
        provider.register("000001", "SSE", [(date(2026, 7, 27), Decimal("10.50"))])
        session, factory, uow_factory = _build_write_session()

        write_stock_daily_bars_raw(
            provider,
            factory,
            symbols=["000001"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=uow_factory,
        )

        record = _attempt_payload(session)["records"][0]
        self.assertEqual(record["symbol"], "000001")
        self.assertEqual(record["exchange"], "SSE")


class WriteStockDailyBarsRawResolutionFailureTest(unittest.TestCase):
    """A bar whose ``instrument_id`` is foreign to the provider must surface as ``LookupError``."""

    def setUp(self) -> None:
        self._session, self._factory, self._uow_factory = _build_write_session()

    def test_unknown_instrument_id_raises_lookup_error(self) -> None:
        foreign_id = InstrumentId.generate()
        attempt_id = uuid4()

        def _fetch(symbols: list[str], start_date: date, end_date: date) -> tuple[Any, Any, Any]:
            orphan_bar = _build_daily_bar(
                instrument_id=foreign_id,
                trade_date=date(2026, 7, 28),
                close=Decimal("3.15"),
                attempt_id=attempt_id,
                observed_at=_FIXED_OBSERVED_AT,
            )
            return _build_provider_response(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                attempt_id=attempt_id,
                records=(orphan_bar,),
            )

        with self.assertRaises(LookupError) as ctx:
            write_stock_daily_bars_raw(
                _InlineProvider(_fetch),
                self._factory,
                symbols=["600519"],
                start_date=date(2026, 7, 28),
                end_date=date(2026, 7, 28),
                unit_of_work_factory=self._uow_factory,
            )
        message = str(ctx.exception)
        self.assertIn("could not resolve instrument_id", message)
        self.assertIn("tushare", message)


class WriteStockDailyBarsRawFailedAttemptTest(unittest.TestCase):
    """A failed attempt must persist request + attempt only; no batch."""

    def setUp(self) -> None:
        self._session, self._factory, self._uow_factory = _build_write_session()

    def test_failed_attempt_creates_no_batch_and_no_daily_bars(self) -> None:
        def _fetch(symbols: list[str], start_date: date, end_date: date) -> tuple[Any, Any, Any]:
            return _build_provider_response(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                attempt_id=uuid4(),
                status=ProviderAttemptStatus.FAILED,
                error_stage=MagicMock(),
                error_code="MALFORMED_PAYLOAD",
                error_message="row 0 trade_date is invalid",
            )

        result = write_stock_daily_bars_raw(
            _InlineProvider(_fetch),
            self._factory,
            symbols=["600519"],
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 28),
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertIsNone(result.batch_id)
        self.assertEqual(result.record_count, 0)

        attempt_rows = [r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)]
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(attempt_rows[0].status, "failed")
        self.assertEqual(attempt_rows[0].error_code, "MALFORMED_PAYLOAD")
        self.assertIsNone(attempt_rows[0].response_payload_json)
        self.assertEqual(_batch_rows(self._session), [])


class WriteStockDailyBarsRawIdempotentRerunTest(unittest.TestCase):
    """A rerun reuses the logical request and grows ``attempt_no``."""

    def setUp(self) -> None:
        self._provider = _TushareStyleStubProvider()
        self._provider.register("600519", "SSE", [(date(2026, 7, 27), Decimal("1800.50"))])
        self._start = date(2026, 7, 27)
        self._end = date(2026, 7, 27)

    def test_rerun_reuses_logical_request_and_appends_attempts(self) -> None:
        session, factory, uow_factory = _build_write_session()

        first = write_stock_daily_bars_raw(
            self._provider,
            factory,
            symbols=["600519"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=uow_factory,
        )
        second = write_stock_daily_bars_raw(
            self._provider,
            factory,
            symbols=["600519"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(first.request_id, second.request_id)
        request_rows = [r for r in session.added_rows if isinstance(r, ProviderRequestRow)]
        self.assertEqual(len(request_rows), 1)

        attempt_rows = [r for r in session.added_rows if isinstance(r, ProviderAttemptRow)]
        self.assertEqual(len(attempt_rows), 2)
        self.assertEqual(sorted(r.attempt_no for r in attempt_rows), [1, 2])

    def test_request_key_default_matches_tushare_dataset(self) -> None:
        # ``dataset_key`` must be ``"stock_daily_bars"`` — the upsert looks the
        # request up by this exact key, so a mismatch surfaces as a silent
        # ``LookupError`` at upsert time.
        session, factory, uow_factory = _build_write_session()

        write_stock_daily_bars_raw(
            self._provider,
            factory,
            symbols=["600519"],
            start_date=self._start,
            end_date=self._end,
            unit_of_work_factory=uow_factory,
        )

        request_rows = [r for r in session.added_rows if isinstance(r, ProviderRequestRow)]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(request_rows[0].provider_key, "tushare")
        self.assertEqual(request_rows[0].dataset_key, "stock_daily_bars")


_BASE_ATTEMPT_START = datetime(2026, 7, 27, 8, 0, 0, tzinfo=UTC)
_BASE_ATTEMPT_FINISH = datetime(2026, 7, 27, 8, 0, 5, tzinfo=UTC)
_REQUEST_KEY = "daily-bars-2026-07-27-2026-07-27-600519"


def _sh_lookup(*, exchange: str, symbol: str) -> Any:
    if (exchange, symbol) not in {("SSE", "600519"), ("SZSE", "000001")}:
        return None
    inst = MagicMock(name="Instrument")
    inst.instrument_id = InstrumentId.generate()
    return inst


def _stock_row(*, symbol: str, exchange: str, close: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "trade_date": "2026-07-27",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "prev_close": close,
        "volume": "1000",
        "amount": "1000000",
        "trading_status": "normal",
    }


def _stock_stored_attempt(
    *,
    attempt_no: int,
    status: str,
    sidecar_records: list[dict[str, Any]],
    provider_request_id: UUID,
    started_at: datetime = _BASE_ATTEMPT_START,
    finished_at: datetime = _BASE_ATTEMPT_FINISH,
) -> StoredProviderAttempt:
    batch_id = uuid4()
    payload = serialize_stock_daily_bars(
        sidecar_records,
        source_batch_id=batch_id,
        observed_at=finished_at,
        provider_key="tushare",
    )
    return StoredProviderAttempt(
        id=batch_id,
        provider_request_id=provider_request_id,
        attempt_no=attempt_no,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        response_payload_sha256="0" * 64,
        response_payload_json=payload,
    )


class UpsertStockDailyBarsLatestAttemptSelectionTest(unittest.TestCase):
    """``upsert_stock_daily_bars`` must pick the LATEST succeeded sidecar."""

    def setUp(self) -> None:
        self._provider_request_id = uuid4()
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key="tushare",
            dataset_key="stock_daily_bars",
            request_key=_REQUEST_KEY,
            request_params={},
            status="succeeded",
        )
        self._session = _build_session()

    def _run_upsert(
        self,
        *,
        attempts: list[StoredProviderAttempt],
        stored_request: StoredProviderRequest | None = None,
        expect_lookup_error: bool = False,
    ) -> tuple[Any, list[list[Any]]]:
        """Drive the upsert service; return ``(summary_or_None, upsert_calls)``."""
        upsert_calls: list[list[Any]] = []
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_UpsertFakeUnitOfWork,
            stored_request=stored_request or self._stored_request,
            attempts=attempts,
            instrument_lookup=_sh_lookup,
            upsert_calls=upsert_calls,
        )
        kwargs = dict(
            provider_key="tushare",
            request_key=_REQUEST_KEY,
            unit_of_work_factory=uow_factory,
        )
        if expect_lookup_error:
            with self.assertRaises(LookupError):
                upsert_stock_daily_bars(_make_session_factory(self._session), **kwargs)
            return None, upsert_calls
        summary = upsert_stock_daily_bars(_make_session_factory(self._session), **kwargs)
        return summary, upsert_calls

    def test_old_then_new_picks_newest(self) -> None:
        old_attempt = _stock_stored_attempt(
            attempt_no=1,
            status="succeeded",
            sidecar_records=[_stock_row(symbol="600519", exchange="SSE", close="1800.50")],
            provider_request_id=self._provider_request_id,
        )
        fresh_attempt = _stock_stored_attempt(
            attempt_no=2,
            status="succeeded",
            sidecar_records=[_stock_row(symbol="600519", exchange="SSE", close="1820.00")],
            provider_request_id=self._provider_request_id,
            started_at=datetime(2026, 7, 27, 9, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 27, 9, 0, 5, tzinfo=UTC),
        )

        summary, upsert_calls = self._run_upsert(attempts=[old_attempt, fresh_attempt])
        self.assertEqual(summary.total, 1)
        bars = upsert_calls[0]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, Decimal("1820.00"))

    def test_unknown_instruments_are_skipped_from_daily_bars(self) -> None:
        # 3 rows: 1 known (600519/SSE), 2 unknown (999999/SZSE + 000001/BADX).
        # The known row reaches ``core.daily_bars``; the others are silently dropped.
        attempt = _stock_stored_attempt(
            attempt_no=1,
            status="succeeded",
            sidecar_records=[
                _stock_row(symbol="600519", exchange="SSE", close="1800.50"),
                _stock_row(symbol="999999", exchange="SZSE", close="9.99"),
                _stock_row(symbol="000001", exchange="BADX", close="10.50"),
            ],
            provider_request_id=self._provider_request_id,
        )

        summary, upsert_calls = self._run_upsert(attempts=[attempt])
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(summary.inserted, 1)
        bars = upsert_calls[0]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].source.source_batch_id, attempt.id)

    def test_only_failed_attempts_raises_lookup_error(self) -> None:
        failed = _stock_stored_attempt(
            attempt_no=1,
            status="failed",
            sidecar_records=[],
            provider_request_id=self._provider_request_id,
        )

        _, upsert_calls = self._run_upsert(attempts=[failed], expect_lookup_error=True)
        self.assertEqual(upsert_calls, [])

    def test_missing_request_row_raises_lookup_error(self) -> None:
        _, upsert_calls = self._run_upsert(
            attempts=[], stored_request=None, expect_lookup_error=True
        )
        self.assertEqual(upsert_calls, [])


class UpsertStockDailyBarsContractTest(unittest.TestCase):
    """The upsert service's public contract: ``request_key`` is mandatory."""

    def test_default_provider_and_dataset_keys_match_tushare(self) -> None:
        # Defaults: ``provider_key='tushare'`` and ``dataset_key='stock_daily_bars'``;
        # without an explicit ``request_key`` the service must refuse loudly — the
        # daily-bars logical key is not derivable from a single date.
        session = _build_session()
        uow_factory = _make_uow_factory(
            session=session,
            uow_cls=_UpsertFakeUnitOfWork,
            stored_request=None,
            attempts=[],
            instrument_lookup=_sh_lookup,
            upsert_calls=[],
        )
        factory = _make_session_factory(session)

        for kwargs in ({}, {"request_key": ""}):
            with self.assertRaises(ValueError) as ctx:
                upsert_stock_daily_bars(factory, unit_of_work_factory=uow_factory, **kwargs)
            self.assertIn("request_key", str(ctx.exception))


_BY_TRADE_DATE_TRADE_DATE = date(2026, 7, 27)


def _build_by_date_daily_bar(
    *,
    instrument_id: InstrumentId,
    trade_date: date,
    close: Decimal,
    attempt_id: UUID,
    observed_at: datetime,
) -> DailyBar:
    """Mirror :func:`_build_daily_bar` for the by-date test set."""

    return DailyBar.build(
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=close,
        high=close + Decimal("0.02"),
        low=close - Decimal("0.02"),
        close=close,
        prev_close=close - Decimal("0.01"),
        volume=Decimal("1000"),
        amount=Decimal("1000000"),
        adjustment=Adjust.NONE,
        trading_status=TradingStatus.NORMAL,
        source=BarSource(
            provider_key="tushare", source_batch_id=attempt_id, observed_at=observed_at
        ),
        revision=1,
    )


class WriteStockDailyBarsRawByTradeDateSidecarTest(unittest.TestCase):
    """The by-date path must stamp ``dataset_key='stock_daily_bars_by_date'``."""

    def setUp(self) -> None:
        self._session, self._factory, self._uow_factory = _build_write_session()
        self._placeholders: dict[tuple[str, str], InstrumentId] = {}
        self._expected_records: list[tuple[str, str, Decimal]] = [
            ("600519", "SSE", Decimal("1800.50")),
            ("000001", "SZSE", Decimal("10.50")),
            ("600000", "SSE", Decimal("8.50")),
        ]
        self._attempt_id = uuid4()
        self._observed = _FIXED_OBSERVED_AT

        def _reverse_lookup(instrument_id: Any) -> tuple[str, str] | None:
            for (symbol, exchange), value in self._placeholders.items():
                if value == instrument_id:
                    return symbol, exchange
            return None

        self._placeholders = {
            (symbol, exchange): InstrumentId.generate()
            for symbol, exchange, _ in self._expected_records
        }

        def _fetch_by_trade_date(trade_date: date) -> tuple[Any, Any, Any]:
            assert trade_date == _BY_TRADE_DATE_TRADE_DATE
            records = tuple(
                _build_by_date_daily_bar(
                    instrument_id=self._placeholders[(symbol, exchange)],
                    trade_date=trade_date,
                    close=close,
                    attempt_id=self._attempt_id,
                    observed_at=self._observed,
                )
                for symbol, exchange, close in self._expected_records
            )
            return _build_by_trade_date_response(
                trade_date=trade_date,
                records=records,
                attempt_id=self._attempt_id,
            )

        self._provider = _ByTradeDateInlineProvider(
            _fetch_by_trade_date, reverse_lookup=_reverse_lookup
        )

    def test_request_key_and_dataset_key_match_by_date_contract(self) -> None:
        result = write_stock_daily_bars_raw_by_trade_date(
            self._provider,
            self._factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(result.record_count, len(self._expected_records))

        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)
        request_row = request_rows[0]
        self.assertEqual(request_row.provider_key, "tushare")
        self.assertEqual(request_row.dataset_key, "stock_daily_bars_by_date")
        self.assertEqual(
            request_row.request_key,
            f"daily-bars-by-date-{_BY_TRADE_DATE_TRADE_DATE.isoformat()}",
        )
        self.assertEqual(
            request_row.request_params,
            {"trade_date": _BY_TRADE_DATE_TRADE_DATE.isoformat()},
        )

    def test_sidecar_records_carry_symbol_and_exchange(self) -> None:
        write_stock_daily_bars_raw_by_trade_date(
            self._provider,
            self._factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        records = _attempt_payload(self._session)["records"]
        self.assertEqual(len(records), len(self._expected_records))

        seen = {(e["symbol"], e["exchange"]) for e in records}
        expected = {(symbol, exchange) for symbol, exchange, _ in self._expected_records}
        self.assertEqual(seen, expected)

        self.assertEqual({e["source_provider"] for e in records}, {"tushare"})

    def test_sidecar_shape_is_byte_compatible_with_per_symbol_path(self) -> None:
        # The by-date and per-symbol entry points share
        # ``_persist_stock_daily_bars_raw``; the sidecar must therefore
        # carry identical keys per record so the downstream
        # ``upsert_stock_daily_bars`` cannot tell which path produced
        # it.
        write_stock_daily_bars_raw_by_trade_date(
            self._provider,
            self._factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        records = _attempt_payload(self._session)["records"]
        expected_keys = {
            "symbol",
            "exchange",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "prev_close",
            "volume",
            "amount",
            "trading_status",
            "source_provider",
            "source_batch_id",
            "observed_at",
        }
        for record in records:
            self.assertEqual(set(record.keys()), expected_keys)


class WriteStockDailyBarsRawByTradeDateFailurePathTest(unittest.TestCase):
    """The by-date path mirrors the per-symbol failure / sidecar / idempotency contract."""

    def setUp(self) -> None:
        self._session, self._factory, self._uow_factory = _build_write_session()

    def test_failed_attempt_creates_no_batch_and_no_daily_bars(self) -> None:
        def _fetch(trade_date: date) -> tuple[Any, Any, Any]:
            return _build_by_trade_date_response(
                trade_date=trade_date,
                records=(),
                attempt_id=uuid4(),
                status=ProviderAttemptStatus.FAILED,
                error_stage=MagicMock(),
                error_code="MALFORMED_PAYLOAD",
                error_message="trade_date missing",
            )

        provider = _ByTradeDateInlineProvider(_fetch)
        result = write_stock_daily_bars_raw_by_trade_date(
            provider,
            self._factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=self._uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertIsNone(result.batch_id)
        self.assertEqual(result.record_count, 0)

        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)
        self.assertEqual(request_rows[0].dataset_key, "stock_daily_bars_by_date")
        self.assertEqual(
            request_rows[0].request_key,
            f"daily-bars-by-date-{_BY_TRADE_DATE_TRADE_DATE.isoformat()}",
        )

        attempt_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 1)
        self.assertEqual(attempt_rows[0].status, "failed")
        self.assertEqual(attempt_rows[0].error_code, "MALFORMED_PAYLOAD")
        self.assertIsNone(attempt_rows[0].response_payload_json)
        self.assertEqual(_batch_rows(self._session), [])

    def test_rerun_reuses_logical_request_and_appends_attempts(self) -> None:
        attempt_id = uuid4()
        records = tuple(
            _build_by_date_daily_bar(
                instrument_id=InstrumentId.generate(),
                trade_date=_BY_TRADE_DATE_TRADE_DATE,
                close=Decimal("1800.50"),
                attempt_id=attempt_id,
                observed_at=_FIXED_OBSERVED_AT,
            )
            for _ in range(2)
        )

        def _fetch(trade_date: date) -> tuple[Any, Any, Any]:
            return _build_by_trade_date_response(
                trade_date=trade_date,
                records=records,
                attempt_id=attempt_id,
            )

        def _lookup(instrument_id: Any) -> tuple[str, str] | None:
            for record in records:
                if record.instrument_id == instrument_id:
                    return ("600519", "SSE")
            return None

        provider = _ByTradeDateInlineProvider(_fetch, reverse_lookup=_lookup)
        factory = self._factory
        uow_factory = self._uow_factory

        first = write_stock_daily_bars_raw_by_trade_date(
            provider,
            factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=uow_factory,
        )
        second = write_stock_daily_bars_raw_by_trade_date(
            provider,
            factory,
            trade_date=_BY_TRADE_DATE_TRADE_DATE,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(first.request_id, second.request_id)
        request_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderRequestRow)
        ]
        self.assertEqual(len(request_rows), 1)

        attempt_rows = [
            r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)
        ]
        self.assertEqual(len(attempt_rows), 2)
        self.assertEqual(sorted(r.attempt_no for r in attempt_rows), [1, 2])

    def test_unknown_instrument_id_raises_lookup_error(self) -> None:
        foreign_id = InstrumentId.generate()
        attempt_id = uuid4()

        def _fetch(trade_date: date) -> tuple[Any, Any, Any]:
            orphan_bar = _build_by_date_daily_bar(
                instrument_id=foreign_id,
                trade_date=trade_date,
                close=Decimal("3.15"),
                attempt_id=attempt_id,
                observed_at=_FIXED_OBSERVED_AT,
            )
            return _build_by_trade_date_response(
                trade_date=trade_date,
                records=(orphan_bar,),
                attempt_id=attempt_id,
            )

        with self.assertRaises(LookupError) as ctx:
            write_stock_daily_bars_raw_by_trade_date(
                _ByTradeDateInlineProvider(_fetch),
                self._factory,
                trade_date=_BY_TRADE_DATE_TRADE_DATE,
                unit_of_work_factory=self._uow_factory,
            )
        message = str(ctx.exception)
        self.assertIn("could not resolve instrument_id", message)
        self.assertIn("tushare", message)


class UpsertStockDailyBarsByTradeDateLookupTest(unittest.TestCase):
    """``upsert_stock_daily_bars`` resolves the by-date request via the logical-key triplet."""

    def setUp(self) -> None:
        self._session = _build_session()
        self._provider_request_id = uuid4()
        self._by_date_request_key = (
            f"daily-bars-by-date-{_BY_TRADE_DATE_TRADE_DATE.isoformat()}"
        )
        self._stored_request = StoredProviderRequest(
            id=self._provider_request_id,
            provider_key="tushare",
            dataset_key="stock_daily_bars_by_date",
            request_key=self._by_date_request_key,
            request_params={"trade_date": _BY_TRADE_DATE_TRADE_DATE.isoformat()},
            status="succeeded",
        )

    def test_upsert_resolves_by_date_request_via_logical_key(self) -> None:
        # Round-trip: the by-date raw writer stamps the same
        # ``(provider_key, dataset_key, request_key)`` the upsert asset
        # looks up by — pin the asset's contract against the persisted
        # request surface.
        attempt_no = 1
        batch_id = uuid4()
        sidecar_records = [
            _stock_row(symbol="600519", exchange="SSE", close="1800.50")
        ]
        payload = serialize_stock_daily_bars(
            sidecar_records,
            source_batch_id=batch_id,
            observed_at=_BASE_ATTEMPT_FINISH,
            provider_key="tushare",
        )
        attempt = StoredProviderAttempt(
            id=batch_id,
            provider_request_id=self._provider_request_id,
            attempt_no=attempt_no,
            started_at=_BASE_ATTEMPT_START,
            finished_at=_BASE_ATTEMPT_FINISH,
            status="succeeded",
            response_payload_sha256="0" * 64,
            response_payload_json=payload,
        )
        upsert_calls: list[list[Any]] = []
        uow_factory = _make_uow_factory(
            session=self._session,
            uow_cls=_UpsertFakeUnitOfWork,
            stored_request=self._stored_request,
            attempts=[attempt],
            instrument_lookup=_sh_lookup,
            upsert_calls=upsert_calls,
        )

        summary = upsert_stock_daily_bars(
            _make_session_factory(self._session),
            provider_key="tushare",
            dataset_key="stock_daily_bars_by_date",
            request_key=self._by_date_request_key,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.inserted, 1)
        bars = upsert_calls[0]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, Decimal("1800.50"))


if __name__ == "__main__":
    unittest.main()
