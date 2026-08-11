"""Tests for the Stage 4B (slice 2) Tushare -> TDX offline fallback orchestration.

The Stage 4B Phase 5 (slice 2) slice adds
:func:`invest_pipeline.stock_daily_bars.write_stock_daily_bars_raw_with_tdx_fallback`,
a thin orchestration helper that wires the existing
:func:`write_stock_daily_bars_raw_by_trade_date` raw write to the
opt-in TDX offline fallback path. The tests in this module pin the
five contracts called out by the slice:

* **Primary success** — a successful (``"succeeded"`` / ``"partial"``)
  Tushare run is the answer even when ``TdxOfflineSettings.enabled``
  is ``True``. The helper never builds a TDX provider, never
  enumerates the universe, never invokes the offline reader. The
  preserved-by-contract ``request_status`` is surfaced verbatim.
* **Fallback success** — a ``"failed"`` Tushare run is followed by a
  successful TDX offline read. The offline provider is built from the
  persisted active ``STOCK`` universe
  (:func:`invest_pipeline.market_breadth_service.list_active_stock_instrument_ids`)
  and the helper returns the TDX ``RawEtlResult``. The
  ``provider_key`` / ``dataset_key`` / ``request_key`` triplet the
  offline provider stamps is the distinct fallback tuple so the
  downstream upsert can resolve whichever provider succeeded.
* **Fallback disabled** — a ``"failed"`` Tushare run surfaces as the
  Tushare failure (``status="failed"``, no batch) when
  ``TdxOfflineSettings.enabled`` is ``False``. The helper never builds
  a TDX provider.
* **Fallback no universe** — a ``"failed"`` Tushare run with TDX
  enabled but an empty persisted active ``STOCK`` universe raises
  :class:`invest_pipeline.market_breadth_service.StockUniverseEmptyError`
  so a misconfigured upstream ``stock_instruments`` materialisation
  surfaces as a hard Dagster failure rather than a partial fallback.
* **Downstream provider resolution** — the ``stock_daily_bars`` asset
  walks the ``("tushare", "stock_daily_bars_by_date")`` /
  ``("tdx_offline", "stock_daily_bars")`` candidates and resolves
  whichever persisted request succeeded. It uses the logical-key
  triplet alone (no Dagster metadata, no second network call).
* **Existing Tushare behaviour preservation** — the
  ``write_stock_daily_bars_raw_by_trade_date`` baseline is unchanged;
  the per-symbol ``write_stock_daily_bars_raw`` baseline is unchanged;
  the existing ``tushare`` ``stock_daily_bars_raw`` / ``stock_daily_bars``
  wiring (primary path, no fallback) is unchanged.

The suite uses the same fake UoW / session helpers
:mod:`tests.unit.test_stock_daily_bars_service` ships so the
orchestration round-trips through the same evidence-tuple persistence
contract without booting a real database.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from invest_domain.instruments.models import InstrumentId, InstrumentType
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttemptStatus,
    ProviderBatchStatus,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.adapters.tdx_offline.config import TdxOfflineSettings
from invest_pipeline.adapters.tdx_offline.stock_adapter import (
    PROVIDER_KEY as TDX_OFFLINE_PROVIDER_KEY,
)
from invest_pipeline.market_breadth_service import StockUniverseEmptyError
from invest_pipeline.stock_daily_bars import (
    TDX_OFFLINE_FALLBACK_DATASET_KEY,
    UpsertSummary,
    write_stock_daily_bars_raw_with_tdx_fallback,
)
from invest_storage.models import ProviderAttemptRow, ProviderRequestRow
from invest_storage.repositories import (
    NewProviderRequest,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderRequest,
)
from sqlalchemy.orm import Session

_FIXED_OBSERVED_AT = datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC)
_TRADE_DATE = date(2026, 7, 28)
_FIXED_INSTRUMENT_IDS: tuple[UUID, ...] = (
    UUID("11111111-1111-1111-1111-111111111111"),
    UUID("22222222-2222-2222-2222-222222222222"),
    UUID("33333333-3333-3333-3333-333333333333"),
)
_FIXED_SYMBOLS: tuple[str, ...] = ("000001", "600519", "000858")
_FIXED_EXCHANGES: tuple[str, ...] = ("SZSE", "SSE", "SZSE")


def _make_daily_bar(
    *,
    symbol: str,
    exchange: str,
    trade_date: date,
    close: Decimal,
    attempt_id: UUID,
    provider_key: str,
) -> DailyBar:
    return DailyBar.build(
        instrument_id=InstrumentId.generate(),
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
            provider_key=provider_key, source_batch_id=attempt_id, observed_at=_FIXED_OBSERVED_AT
        ),
        revision=1,
    )


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


class _WritePathFakeUoW:
    """Capture every ``provider_*`` write the helper makes; share one request log across UoWs.

    Mirrors the ``_FakeUnitOfWork`` the Slice 1 / 2 service tests use,
    plus the bulk
    :meth:`SqlAlchemyInstrumentRepository.get_many_by_ids` lookup the
    fallback orchestration needs to enumerate the persisted active
    ``STOCK`` universe's naked ``symbol`` strings.
    """

    def __init__(
        self,
        session: MagicMock,
        *,
        request_log: list[ProviderRequestRow],
        active_symbol_by_id: dict[UUID, str],
    ) -> None:
        self._session = session
        self._request_log = request_log
        self._active_symbol_by_id = active_symbol_by_id
        self._provider_requests = SqlAlchemyProviderRequestRepository(session)
        self._provider_requests.get_or_create = self._get_or_create  # type: ignore[method-assign]
        self._provider_attempts = SqlAlchemyProviderAttemptRepository(session)
        self._provider_attempts.list_by_request = self._list_by_request  # type: ignore[method-assign]
        self._provider_batches = SqlAlchemyProviderBatchRepository(session)
        self._instruments = SqlAlchemyInstrumentRepository(session)
        self._instruments.get_many_by_ids = self._get_many_by_ids  # type: ignore[method-assign]
        self._instruments.get_by_business_key = MagicMock(return_value=None)  # type: ignore[method-assign]

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

    def _get_many_by_ids(self, ids: list[UUID]) -> dict[UUID, Any]:
        # Build a deterministic ``Instrument`` for every persisted
        # ``STOCK`` id the orchestration hands us. The orchestration
        # only consumes the ``symbol`` field, so the rest of the model
        # is filled with deterministic placeholders that match the
        # ``StockUniverseEmptyError``-fail-closed contract.
        out: dict[UUID, Any] = {}
        for instrument_id in ids:
            symbol = self._active_symbol_by_id.get(instrument_id)
            if symbol is None:
                continue
            out[instrument_id] = MagicMock(
                symbol=symbol,
                exchange="SSE" if symbol.startswith(("5", "6")) else "SZSE",
                instrument_type=InstrumentType.STOCK,
                is_active=True,
                instrument_id=InstrumentId(instrument_id),
                name=f"name-{symbol}",
            )
        return out

    provider_requests = property(lambda self: self._provider_requests)
    provider_attempts = property(lambda self: self._provider_attempts)
    provider_batches = property(lambda self: self._provider_batches)
    instruments = property(lambda self: self._instruments)
    session = property(lambda self: self._session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> _WritePathFakeUoW:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self._session.close()


class _ReadPathFakeUoW:
    """Read-only UoW for the ``list_active_stock_instrument_ids`` lookup."""

    def __init__(
        self,
        session: MagicMock,
        *,
        active_instrument_ids: list[UUID],
    ) -> None:
        self._session = session
        self._active_instrument_ids = active_instrument_ids
        self._instruments = SqlAlchemyInstrumentRepository(session)

    def session(self) -> Session:  # pragma: no cover - mirror UoW surface
        return self._session

    def _list_active_stocks(self) -> list[UUID]:
        return list(self._active_instrument_ids)

    instruments = property(lambda self: self._instruments)

    def __enter__(self) -> _ReadPathFakeUoW:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._session.close()


def _build_session() -> MagicMock:
    session = MagicMock(name="Session", spec=Session)
    session.added_rows = []
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


def _make_uow_factory(
    session: MagicMock,
    *,
    uow_cls: type,
    **kwargs: Any,
) -> MagicMock:
    def _factory(*_a: Any, **_k: Any) -> Any:
        return uow_cls(session, **kwargs)

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


class _TushareInlineProvider:
    """Inline provider stub for the by-trade-date path.

    Mirrors :class:`_StockByTradeDateProviderPort` — ``fetch_daily_bars_by_trade_date``
    plus ``symbol_and_exchange_for_instrument_id`` plus
    ``provider_key`` — and lets the caller script the (request,
    attempt, batch) triple the raw writer will see. The reverse-lookup
    table is populated from ``register_symbol`` so the application
    service can resolve every bar's ``(symbol, exchange)`` pair via
    the same reverse-lookup the real Tushare adapter exposes.
    """

    def __init__(
        self,
        *,
        request_status: str,
        attempt_status: ProviderAttemptStatus = ProviderAttemptStatus.SUCCEEDED,
        records: tuple[DailyBar, ...] = (),
        provider_key: str = "tushare",
        dataset_key: str = "stock_daily_bars_by_date",
        request_key: str = "daily-bars-by-date-2026-07-28",
        error_code: str | None = None,
        error_message: str | None = None,
        batch: Any = "auto",
    ) -> None:
        self._request_status = request_status
        self._attempt_status = attempt_status
        self._records = records
        self._provider_key = provider_key
        self._dataset_key = dataset_key
        self._request_key = request_key
        self._error_code = error_code
        self._error_message = error_message
        # ``batch="auto"`` derives ``None`` for ``request_status="partial"``
        # and a :class:`MagicMock` batch otherwise; callers can override
        # the derivation by passing an explicit ``batch=...`` value so
        # failure / partial / succeeded shapes stay scriptable.
        if batch == "auto":
            self._batch: Any = None if request_status == "partial" else "auto"
        else:
            self._batch = batch
        self.fetch_calls = 0
        self._ids: dict[tuple[str, str], InstrumentId] = {}
        for bar in records:
            source_key = bar.source.source_batch_id
            self._ids[(str(source_key), "tushare")] = bar.instrument_id

    def register_symbol(self, symbol: str, exchange: str, instrument_id: InstrumentId) -> None:
        self._ids[(symbol, exchange)] = instrument_id

    @property
    def provider_key(self) -> str:
        return self._provider_key

    def fetch_daily_bars_by_trade_date(self, trade_date: date) -> tuple[Any, Any, Any]:
        self.fetch_calls += 1
        request = MagicMock(
            provider_key=self._provider_key,
            dataset_key=self._dataset_key,
            request_key=self._request_key,
            params={"trade_date": trade_date.isoformat()},
        )
        attempt = MagicMock(
            attempt_number=1,
            status=self._attempt_status,
            started_at=_FIXED_OBSERVED_AT,
            finished_at=_FIXED_OBSERVED_AT,
            error_stage=None,
            error_code=self._error_code,
            error_message=self._error_message,
        )
        if self._attempt_status is ProviderAttemptStatus.FAILED:
            return request, attempt, None
        batch_value = self._batch
        if batch_value == "auto":
            batch_value = MagicMock(
                records=self._records,
                raw_payload_hash="0" * 64,
                status=ProviderBatchStatus.SUCCEEDED,
                warnings=(),
            )
        return request, attempt, batch_value

    def symbol_and_exchange_for_instrument_id(self, instrument_id: Any) -> tuple[str, str] | None:
        for (symbol, exchange), value in self._ids.items():
            if value == instrument_id:
                return symbol, exchange
        return None


def _make_write_uow_factory(
    session: MagicMock,
    *,
    active_symbol_by_id: dict[UUID, str] | None = None,
    request_log: list[ProviderRequestRow] | None = None,
) -> MagicMock:
    return _make_uow_factory(
        session,
        uow_cls=_WritePathFakeUoW,
        active_symbol_by_id=active_symbol_by_id
        or dict(zip(_FIXED_INSTRUMENT_IDS, _FIXED_SYMBOLS, strict=True)),
        request_log=request_log if request_log is not None else [],
    )


def _make_universe_enumerator(
    instrument_ids: list[UUID] | None = None,
) -> Any:
    """Build a callable the orchestration helper consumes as the test seam.

    The callable returns the storage-side ``instrument_id`` UUIDs the
    helper passes to ``_resolve_active_stock_symbols``; tests inject a
    fixed list so the suite never has to mock the SQLAlchemy session
    the production default
    (:func:`invest_pipeline.market_breadth_service.list_active_stock_instrument_ids`)
    reaches into.
    """

    return lambda: list(
        instrument_ids if instrument_ids is not None else list(_FIXED_INSTRUMENT_IDS)
    )


class _TdxProviderFactorySpy:
    """Spy that records the (settings, symbols) the orchestration passes in.

    Mirrors the ``tdx_provider_factory`` keyword the helper accepts so
    the suite can introspect what symbols the universe enumeration
    produced without ever touching the operator-managed ``vipdoc``
    tree. The returned :class:`TdxOfflineStockProvider` is a
    double that pre-populates a ``(symbol, exchange) -> InstrumentId``
    placeholder cache for every symbol the orchestration hands it,
    matching the structural contract the application-service sidecar
    helper expects so the raw write can persist a fully-formed
    sidecar without a real ``vipdoc`` filesystem behind it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[TdxOfflineSettings, list[str]]] = []

    def __call__(
        self,
        *,
        settings: TdxOfflineSettings,
        symbols: list[str],
    ) -> Any:
        self.calls.append((settings, list(symbols)))
        provider = MagicMock(name="TdxOfflineStockProvider")
        provider.provider_key = TDX_OFFLINE_PROVIDER_KEY
        attempt_id = uuid4()
        placeholder_by_id: dict[InstrumentId, tuple[str, str]] = {}
        records: list[DailyBar] = []
        for symbol in symbols:
            exchange = "SSE" if symbol.startswith(("5", "6")) else "SZSE"
            placeholder = InstrumentId.generate()
            placeholder_by_id[placeholder] = (symbol, exchange)
            records.append(
                _make_daily_bar(
                    symbol=symbol,
                    exchange=exchange,
                    trade_date=_TRADE_DATE,
                    close=Decimal("10.00"),
                    attempt_id=attempt_id,
                    provider_key=TDX_OFFLINE_PROVIDER_KEY,
                ).__class__.build(
                    instrument_id=placeholder,
                    trade_date=_TRADE_DATE,
                    open=Decimal("10.00"),
                    high=Decimal("10.02"),
                    low=Decimal("9.98"),
                    close=Decimal("10.00"),
                    prev_close=Decimal("9.99"),
                    volume=Decimal("1000"),
                    amount=Decimal("1000000"),
                    adjustment=Adjust.NONE,
                    trading_status=TradingStatus.NORMAL,
                    source=BarSource(
                        provider_key=TDX_OFFLINE_PROVIDER_KEY,
                        source_batch_id=attempt_id,
                        observed_at=_FIXED_OBSERVED_AT,
                    ),
                    revision=1,
                )
            )
        request = MagicMock(
            provider_key=TDX_OFFLINE_PROVIDER_KEY,
            dataset_key=TDX_OFFLINE_FALLBACK_DATASET_KEY,
            request_key=f"daily-bars-by-date-{_TRADE_DATE.isoformat()}",
            params={"trade_date": _TRADE_DATE.isoformat()},
        )
        attempt = MagicMock(
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=_FIXED_OBSERVED_AT,
            finished_at=_FIXED_OBSERVED_AT,
        )
        batch = MagicMock(
            records=tuple(records),
            raw_payload_hash="0" * 64,
            status=ProviderBatchStatus.SUCCEEDED,
            warnings=(),
        )
        provider.fetch_daily_bars_by_trade_date = MagicMock(  # type: ignore[method-assign]
            return_value=(request, attempt, batch)
        )

        def _reverse_lookup(instrument_id: Any) -> tuple[str, str] | None:
            for key, value in placeholder_by_id.items():
                if key == instrument_id or (getattr(instrument_id, "value", None) == key.value):
                    return value
            return None

        provider.symbol_and_exchange_for_instrument_id = MagicMock(  # type: ignore[method-assign]
            side_effect=_reverse_lookup
        )
        return provider


class PrimarySuccessTest(unittest.TestCase):
    """A successful / partial Tushare run is always the answer."""

    def test_tushare_succeeded_returns_tushare_result_without_consulting_tdx(self) -> None:
        bar = _make_daily_bar(
            symbol="000001",
            exchange="SZSE",
            trade_date=_TRADE_DATE,
            close=Decimal("10.50"),
            attempt_id=uuid4(),
            provider_key="tushare",
        )
        tushare = _TushareInlineProvider(
            request_status="succeeded",
            records=(bar,),
        )
        tushare.register_symbol("000001", "SZSE", bar.instrument_id)
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        universe_calls: list[None] = []

        def _make_enumerator() -> list[UUID]:
            universe_calls.append(None)
            return list(_FIXED_INSTRUMENT_IDS)

        enumerator = _make_enumerator

        result = write_stock_daily_bars_raw_with_tdx_fallback(
            tushare,
            factory,
            trade_date=_TRADE_DATE,
            tdx_settings=settings,
            tdx_provider_factory=tdx_spy,
            universe_enumerator=enumerator,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(tushare.fetch_calls, 1)
        self.assertEqual(
            tdx_spy.calls,
            [],
            "TDX provider must not be built on a successful Tushare run",
        )
        self.assertEqual(
            universe_calls,
            [],
            "universe enumeration must be skipped on a non-failed Tushare run",
        )

    def test_tushare_partial_returns_tushare_result_without_consulting_tdx(self) -> None:
        # ``partial`` (no batch row) is also a non-failed result; the
        # fallback must NEVER consult the offline adapter on a partial
        # primary so a degraded Tushare partial run is not silently
        # overwritten by a less-fresh offline read.
        tushare = _TushareInlineProvider(
            request_status="partial",
            attempt_status=ProviderAttemptStatus.SUCCEEDED,
            records=(),
        )
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        universe_calls: list[None] = []

        def _make_enumerator() -> list[UUID]:
            universe_calls.append(None)
            return list(_FIXED_INSTRUMENT_IDS)

        enumerator = _make_enumerator

        result = write_stock_daily_bars_raw_with_tdx_fallback(
            tushare,
            factory,
            trade_date=_TRADE_DATE,
            tdx_settings=settings,
            tdx_provider_factory=tdx_spy,
            universe_enumerator=enumerator,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(result.request_status, "partial")
        self.assertEqual(
            tdx_spy.calls,
            [],
            "TDX provider must not be built on a partial Tushare run",
        )
        self.assertEqual(
            universe_calls,
            [],
            "universe enumeration must be skipped on a partial Tushare run",
        )


class FallbackSuccessTest(unittest.TestCase):
    """A failed Tushare run is followed by a successful TDX offline read."""

    def test_tushare_failed_tdx_enabled_returns_tdx_result(self) -> None:
        tushare = _TushareInlineProvider(
            request_status="failed",
            attempt_status=ProviderAttemptStatus.FAILED,
            error_code="MALFORMED_PAYLOAD",
            error_message="row 0 trade_date is invalid",
        )
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        enumerator = _make_universe_enumerator()

        result = write_stock_daily_bars_raw_with_tdx_fallback(
            tushare,
            factory,
            trade_date=_TRADE_DATE,
            tdx_settings=settings,
            tdx_provider_factory=tdx_spy,
            universe_enumerator=enumerator,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(tushare.fetch_calls, 1)
        self.assertEqual(len(tdx_spy.calls), 1)
        observed_settings, observed_symbols = tdx_spy.calls[0]
        self.assertIs(observed_settings, settings)
        self.assertEqual(set(observed_symbols), set(_FIXED_SYMBOLS))

    def test_tdx_provider_receives_active_stock_universe_only(self) -> None:
        # The offline reader must receive the persisted active ``STOCK``
        # universe the dynamic ``stock_input_snapshot`` materialises —
        # not a stale ``config/stock-universe.yaml`` snapshot. The
        # helper delegates to
        # ``list_active_stock_instrument_ids`` (the dynamic-universe
        # source) which returns the storage-side ``instrument_id``
        # UUIDs; the helper then resolves them to naked symbols via
        # ``SqlAlchemyInstrumentRepository.get_many_by_ids``.
        tushare = _TushareInlineProvider(
            request_status="failed",
            attempt_status=ProviderAttemptStatus.FAILED,
        )
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        enumerator = _make_universe_enumerator()

        write_stock_daily_bars_raw_with_tdx_fallback(
            tushare,
            factory,
            trade_date=_TRADE_DATE,
            tdx_settings=settings,
            tdx_provider_factory=tdx_spy,
            universe_enumerator=enumerator,
            unit_of_work_factory=uow_factory,
        )
        observed_symbols = sorted(tdx_spy.calls[0][1])
        self.assertEqual(observed_symbols, sorted(_FIXED_SYMBOLS))


class FallbackDisabledTest(unittest.TestCase):
    """TDX disabled returns the Tushare failure verbatim."""

    def test_tushare_failed_tdx_disabled_returns_tushare_failure(self) -> None:
        tushare = _TushareInlineProvider(
            request_status="failed",
            attempt_status=ProviderAttemptStatus.FAILED,
            error_code="MALFORMED_PAYLOAD",
            error_message="row 0 trade_date is invalid",
        )
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=False, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        universe_calls: list[None] = []

        def _make_enumerator() -> list[UUID]:
            universe_calls.append(None)
            return list(_FIXED_INSTRUMENT_IDS)

        enumerator = _make_enumerator

        result = write_stock_daily_bars_raw_with_tdx_fallback(
            tushare,
            factory,
            trade_date=_TRADE_DATE,
            tdx_settings=settings,
            tdx_provider_factory=tdx_spy,
            universe_enumerator=enumerator,
            unit_of_work_factory=uow_factory,
        )

        self.assertEqual(result.request_status, "failed")
        self.assertEqual(result.attempt_status, "failed")
        self.assertEqual(
            tdx_spy.calls,
            [],
            "TDX provider must not be built when TdxOfflineSettings.enabled is False",
        )
        self.assertEqual(
            universe_calls,
            [],
            "universe enumeration must be skipped when TDX is disabled",
        )


class FallbackNoUniverseTest(unittest.TestCase):
    """TDX enabled but empty universe raises :class:`StockUniverseEmptyError`."""

    def test_empty_persisted_active_stock_universe_raises_stock_universe_empty_error(self) -> None:
        tushare = _TushareInlineProvider(
            request_status="failed",
            attempt_status=ProviderAttemptStatus.FAILED,
        )
        tdx_spy = _TdxProviderFactorySpy()
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session, active_symbol_by_id={})
        # Universe enumeration returns ``[]`` — the helper must raise
        # instead of building an empty TDX provider.
        enumerator = _make_universe_enumerator(instrument_ids=[])

        with self.assertRaises(StockUniverseEmptyError) as ctx:
            write_stock_daily_bars_raw_with_tdx_fallback(
                tushare,
                factory,
                trade_date=_TRADE_DATE,
                tdx_settings=settings,
                tdx_provider_factory=tdx_spy,
                universe_enumerator=enumerator,
                unit_of_work_factory=uow_factory,
            )
        self.assertIn(
            "tdx_offline fallback for trade_date=2026-07-28 requires "
            "a non-empty active STOCK universe",
            str(ctx.exception),
        )
        self.assertEqual(
            tdx_spy.calls,
            [],
            "TDX provider must not be built when the universe is empty",
        )


class DownstreamProviderResolutionTest(unittest.TestCase):
    """``upsert_stock_daily_bars`` resolves whichever provider produced the successful attempt.

    The downstream ``stock_daily_bars`` asset must walk the
    ``("tushare", "stock_daily_bars_by_date")`` /
    ``("tdx_offline", "stock_daily_bars")`` candidates in priority
    order and resolve the persisted request whose ``status`` is not
    ``"failed"``. The lookup uses the logical-key triplet alone — no
    Dagster metadata, no second network call — so the asset metadata
    surfaces the resolved ``provider_key`` and the
    :func:`upsert_stock_daily_bars` call is invoked with the matching
    ``provider_key`` / ``dataset_key`` pair.
    """

    def _upsert_with_candidate(self, candidate_status: dict[tuple[str, str], str]) -> Any:
        """Build a UoW + spy that returns ``candidate_status`` for each candidate tuple.

        ``candidate_status`` maps ``(provider_key, dataset_key)`` to
        ``"succeeded"`` / ``"failed"`` / ``"missing"``; the UoW returns
        the matching :class:`StoredProviderRequest` so the downstream
        resolution code picks the first non-failed row.
        """
        captured: dict[str, Any] = {}

        def _get_by_logical_key(
            *, provider_key: str, dataset_key: str, request_key: str
        ) -> StoredProviderRequest | None:
            status = candidate_status.get((provider_key, dataset_key))
            if status == "missing":
                return None
            row_id = uuid4()
            row = ProviderRequestRow(
                id=row_id,
                provider_key=provider_key,
                dataset_key=dataset_key,
                request_key=request_key,
                request_params={},
                requested_by_run_id=None,
                status=status,
            )
            return _stored_request(row)

        session = _build_session()
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.provider_requests.get_by_logical_key = MagicMock(side_effect=_get_by_logical_key)
        uow.daily_bars.upsert_many = MagicMock(return_value=[])
        uow.instruments.get_by_business_key = MagicMock(return_value=None)

        def _upsert(
            session_factory: Any,
            *,
            provider_key: str = "tushare",
            dataset_key: str = "stock_daily_bars",
            request_key: str | None = None,
            unit_of_work_factory: Any = None,
        ) -> UpsertSummary:
            captured["provider_key"] = provider_key
            captured["dataset_key"] = dataset_key
            captured["request_key"] = request_key
            return UpsertSummary(inserted=0, skipped=0)

        return session, uow, _upsert, captured

    def test_resolves_tdx_offline_when_tushare_failed(self) -> None:
        from invest_pipeline.assets import stock_daily_bars as _asset_fn

        session, uow, upsert_fn, captured = self._upsert_with_candidate(
            {
                ("tushare", "stock_daily_bars_by_date"): "failed",
                ("tdx_offline", "stock_daily_bars"): "succeeded",
            }
        )
        engine = MagicMock()
        with (
            patch_build_engine(engine),
            patch_session_factory(session),
            patch_build_stock_provider(),
            patch_uow_factory(uow),
            patch_upsert(upsert_fn),
        ):
            result = _invoke_stock_daily_bars_asset(_asset_fn, partition_key="2026-07-28")

        self.assertEqual(captured["provider_key"], "tdx_offline")
        self.assertEqual(captured["dataset_key"], "stock_daily_bars")
        self.assertEqual(
            captured["request_key"],
            f"daily-bars-by-date-{_TRADE_DATE.isoformat()}",
        )
        self.assertEqual(result.metadata["provider"], "tdx_offline")
        # ``skipped_asset`` is only set when the resolution surfaces a
        # skipped result; the success path leaves the key absent.
        self.assertNotIn("skipped_asset", result.metadata)

    def test_resolves_tushare_when_tushare_succeeded(self) -> None:
        from invest_pipeline.assets import stock_daily_bars as _asset_fn

        session, uow, upsert_fn, captured = self._upsert_with_candidate(
            {
                ("tushare", "stock_daily_bars_by_date"): "succeeded",
                ("tdx_offline", "stock_daily_bars"): "missing",
            }
        )
        engine = MagicMock()
        with (
            patch_build_engine(engine),
            patch_session_factory(session),
            patch_build_stock_provider(),
            patch_uow_factory(uow),
            patch_upsert(upsert_fn),
        ):
            result = _invoke_stock_daily_bars_asset(_asset_fn, partition_key="2026-07-28")

        self.assertEqual(captured["provider_key"], "tushare")
        self.assertEqual(captured["dataset_key"], "stock_daily_bars_by_date")
        self.assertEqual(result.metadata["provider"], "tushare")
        self.assertNotIn("skipped_asset", result.metadata)

    def test_skips_when_both_candidates_missing_or_failed(self) -> None:
        from invest_pipeline.assets import stock_daily_bars as _asset_fn

        session, uow, upsert_fn, captured = self._upsert_with_candidate(
            {
                ("tushare", "stock_daily_bars_by_date"): "failed",
                ("tdx_offline", "stock_daily_bars"): "missing",
            }
        )
        engine = MagicMock()
        with (
            patch_build_engine(engine),
            patch_session_factory(session),
            patch_build_stock_provider(),
            patch_uow_factory(uow),
            patch_upsert(upsert_fn),
        ):
            result = _invoke_stock_daily_bars_asset(_asset_fn, partition_key="2026-07-28")

        self.assertEqual(captured, {}, "upsert_stock_daily_bars must not be called")
        self.assertTrue(result.metadata["skipped_asset"])
        self.assertEqual(result.metadata["inserted"], 0)
        self.assertEqual(result.metadata["skipped"], 0)

    def test_skips_when_both_candidates_failed(self) -> None:
        from invest_pipeline.assets import stock_daily_bars as _asset_fn

        session, uow, upsert_fn, captured = self._upsert_with_candidate(
            {
                ("tushare", "stock_daily_bars_by_date"): "failed",
                ("tdx_offline", "stock_daily_bars"): "failed",
            }
        )
        engine = MagicMock()
        with (
            patch_build_engine(engine),
            patch_session_factory(session),
            patch_build_stock_provider(),
            patch_uow_factory(uow),
            patch_upsert(upsert_fn),
        ):
            result = _invoke_stock_daily_bars_asset(_asset_fn, partition_key="2026-07-28")

        self.assertEqual(captured, {})
        self.assertTrue(result.metadata["skipped_asset"])
        self.assertEqual(result.metadata["reason"], "upstream attempt failed or missing")


class ExistingTushareBehaviourTest(unittest.TestCase):
    """The Tushare primary ``stock_daily_bars_raw`` wiring is unchanged."""

    def test_tushare_primary_path_does_not_invoke_orchestration_helper(self) -> None:
        # The Slice 1 / Slice 4B-A by-date path is unchanged: the
        # Tushare ``StockTushareProvider.fetch_daily_bars_by_trade_date``
        # capability is still wired through
        # ``write_stock_daily_bars_raw_by_trade_date``; only the new
        # fallback orchestration helper additionally consults TDX on a
        # ``"failed"`` Tushare run.
        session = _build_session()
        factory = _make_session_factory(session)
        uow_factory = _make_write_uow_factory(session)
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/tmp/opencode/tdx-fallback"))

        captured_calls: list[dict[str, Any]] = []

        def _spy(*_args: Any, **kwargs: Any) -> Any:
            captured_calls.append(kwargs)
            return SimpleNamespace(
                request_id=uuid4(),
                attempt_id=uuid4(),
                batch_id=uuid4(),
                request_status="succeeded",
                attempt_status="succeeded",
                record_count=1,
            )

        # Patching the underlying baseline helper pins the Tushare
        # primary path's behaviour: the orchestration helper is what
        # consults TDX, not the baseline.
        with patch(
            "invest_pipeline.stock_daily_bars.write_stock_daily_bars_raw_by_trade_date",
            side_effect=_spy,
        ):
            bar = _make_daily_bar(
                symbol="000001",
                exchange="SZSE",
                trade_date=_TRADE_DATE,
                close=Decimal("10.50"),
                attempt_id=uuid4(),
                provider_key="tushare",
            )
            tushare = _TushareInlineProvider(
                request_status="succeeded",
                records=(bar,),
            )
            tushare.register_symbol("000001", "SZSE", bar.instrument_id)
            write_stock_daily_bars_raw_with_tdx_fallback(
                tushare,
                factory,
                trade_date=_TRADE_DATE,
                tdx_settings=settings,
                tdx_provider_factory=_TdxProviderFactorySpy(),
                universe_enumerator=_make_universe_enumerator(),
                unit_of_work_factory=uow_factory,
            )
        self.assertEqual(
            len(captured_calls),
            1,
            "primary Tushare write must be called exactly once",
        )


def patch_build_engine(engine: MagicMock) -> Any:
    from invest_pipeline import assets

    return patch.object(assets, "build_engine", lambda _url: engine)


def patch_session_factory(session: MagicMock) -> Any:
    from invest_pipeline import assets

    return patch.object(assets, "session_factory", lambda _engine: MagicMock(return_value=session))


def patch_uow_factory(uow: MagicMock) -> Any:
    import invest_storage

    return patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _f: uow)


def patch_build_stock_provider(provider_key: str = "tushare") -> Any:
    from invest_pipeline import assets

    provider = MagicMock(name="StockTushareProvider")
    provider.provider_key = provider_key
    return patch.object(assets, "build_stock_provider", lambda _settings: provider)


def patch_upsert(upsert_fn: Any) -> Any:
    from invest_pipeline import assets

    return patch.object(assets, "upsert_stock_daily_bars", upsert_fn)


def _invoke_stock_daily_bars_asset(asset_fn: Any, *, partition_key: str) -> Any:
    """Invoke the ``stock_daily_bars`` underlying callable with a partition context."""
    import dagster as dg
    from invest_pipeline import assets

    underlying = assets.stock_daily_bars.op.compute_fn.decorated_fn
    return underlying(dg.build_asset_context(partition_key=partition_key))


if __name__ == "__main__":
    unittest.main()
