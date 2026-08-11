"""Focused offline tests for the TDX ``.day`` offline stock provider.

The Stage 4B Phase 5 (slice 1) Tushare → TDX offline fallback seam
is intentionally narrow: a drop-in provider that translates one
``.day`` file per ``(symbol, market)`` pair into the
``ProviderRequest`` / ``ProviderAttempt`` / ``ProviderBatch``
evidence tuple the existing
:func:`invest_pipeline.stock_daily_bars.write_stock_daily_bars_raw`
helper already consumes. The tests pin four invariants:

* **Success path** — a valid ``vipdoc/sh/lday/sh600000.day`` file
  produces a ``SUCCEEDED`` :class:`ProviderAttempt` whose
  :class:`ProviderBatch` carries one :class:`DailyBar` per record
  with prices / amount preserved as :class:`decimal.Decimal` and the
  audit :class:`BarSource` stamped with ``provider_key="tdx_offline"``.
  The reverse-lookup contract
  (:meth:`TdxOfflineStockProvider.symbol_and_exchange_for_instrument_id`)
  resolves the placeholder ``InstrumentId`` back to the
  ``(symbol, exchange)`` pair so the upstream service can
  correlate audit fields without inferring the exchange from the
  symbol prefix.
* **Missing / invalid file** — a missing ``.day`` file surfaces as a
  ``FAILED`` :class:`ProviderAttempt` with the typed
  :class:`ProviderFailureStage.STORAGE` and a deterministic
  ``error_code`` (e.g. ``"tdx_file_missing"``). The provider
  refuses to fabricate a batch so the application service can
  route the failure as a normal provider error.
* **Disabled / no-universe / record-cap guard** — a provider
  constructed with default ``enabled=False`` and one with no
  registered universe both surface as ``FAILED`` with deterministic
  error codes; the record-cap guard short-circuits a run that
  would otherwise flood the sidecar.
* **Primary provider preservation** — the catalog keeps the Tushare
  declaration as ``has_runtime_factory_adapter=True``; the new
  ``TDX_OFFLINE`` declaration is catalog-only and disabled by
  default. The Tushare adapter's existing ``stock_daily_bars_raw``
  wiring is unchanged.
* **Phase 1A (TDX production fallback)** — Beijing (``bj``) and
  the market-qualified pair path. The provider accepts an explicit
  ``(market, symbol)`` pair via :meth:`register_pair` and
  :meth:`fetch_daily_bars_by_pairs`, and exposes a read-only
  :meth:`discover_symbols` method that scans the operator's
  ``vipdoc`` tree for the by-date fallback. The existing
  :meth:`register_symbol` / :meth:`fetch_daily_bars` callers
  continue to work — the prefix-based heuristic still routes
  ``5`` / ``6`` symbols to ``sh`` and everything else to ``sz``.

Slice 1 deliberately does **not** wire the runtime fallback into
the ``stock_daily_bars_raw`` Dagster asset — the asset-level
fallback orchestration is a follow-up that requires a
symbol-enumeration contract. Phase 1A (this slice) adds the
market-qualified pair path and the read-only ``discover_symbols``
helper; the asset wiring itself remains a follow-up.
"""

from __future__ import annotations

import json
import struct
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
    ProviderFailureStage,
)
from invest_pipeline.adapters.tdx_offline import (
    DATASET_KEY,
    PROVIDER_KEY,
    TdxOfflineSettings,
    TdxOfflineStockProvider,
)
from invest_pipeline.adapters.tdx_offline.config import TdxOfflineSettings as _SettingsReimport
from invest_pipeline.adapters.tdx_offline.stock_adapter import (
    TdxOfflineStockProvider as _AdapterReimport,
)
from invest_pipeline.provider_catalog import (
    FIXTURE_DEV,
    HITHINK,
    TDX_OFFLINE,
    TUSHARE,
    iter_provider_declarations,
    lookup_provider,
    runtime_supported_provider_keys,
)


def _build_record(
    date_yyyymmdd: int,
    open_raw: int,
    high_raw: int,
    low_raw: int,
    close_raw: int,
    amount_f32: float,
    volume_raw: int,
    reserved: bytes = b"\x00\x00\x00\x00",
) -> bytes:
    payload = struct.pack(
        "<5IfI",
        date_yyyymmdd,
        open_raw,
        high_raw,
        low_raw,
        close_raw,
        amount_f32,
        volume_raw,
    )
    assert len(payload) == 28
    assert len(reserved) == 4
    return payload + reserved


def _write_symbol_file(tmp_path: Path, market: str, symbol: str, payload: bytes) -> Path:
    base = tmp_path / "vipdoc" / market / "lday"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{market}{symbol}.day"
    target.write_bytes(payload)
    return target


_FIXED_OBSERVED_AT = datetime(2026, 7, 28, 8, 0, 0, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return _FIXED_OBSERVED_AT


class PublicSurfaceTest(unittest.TestCase):
    """``TdxOfflineSettings`` / ``TdxOfflineStockProvider`` export the frozen surface."""

    def test_settings_class_is_re_exported(self) -> None:
        self.assertIs(TdxOfflineSettings, _SettingsReimport)

    def test_provider_class_is_re_exported(self) -> None:
        self.assertIs(TdxOfflineStockProvider, _AdapterReimport)

    def test_provider_key_and_dataset_key_match_reader_constants(self) -> None:
        # The provider stamp on the evidence tuple must match the
        # reader module's frozen constants so a persisted
        # ``raw.provider_requests`` row can be correlated with the
        # catalog entry by logical key alone.
        self.assertEqual(PROVIDER_KEY, "tdx_offline")
        self.assertEqual(DATASET_KEY, "stock_daily_bars")

    def test_default_settings_are_disabled_with_safe_data_root(self) -> None:
        # Fail-closed default: ``enabled=False`` so a stray operator
        # directory cannot leak into the daily-bars evidence model.
        settings = TdxOfflineSettings()
        self.assertFalse(settings.enabled)
        self.assertIsInstance(settings.data_root, Path)
        self.assertGreaterEqual(settings.record_cap, 0)

    def test_settings_repr_redacts_data_root(self) -> None:
        # The path is operator-managed but never a secret; the
        # redaction policy mirrors Cifang / Tushare (``"***"``) so
        # accidental ``format(settings)`` or ``log.info(settings)``
        # cannot leak deployment detail.
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/var/lib/tdx/vipdoc"))
        rendered = repr(settings)
        self.assertIn("'***'", rendered)
        self.assertNotIn("/var/lib/tdx/vipdoc", rendered)

    def test_settings_redacted_dict_redacts_data_root(self) -> None:
        settings = TdxOfflineSettings(enabled=True, data_root=Path("/var/lib/tdx/vipdoc"))
        redacted = settings.redacted_dict()
        self.assertEqual(redacted["data_root"], "***")
        self.assertEqual(redacted["provider_key"], PROVIDER_KEY)
        self.assertEqual(redacted["dataset_key"], DATASET_KEY)
        self.assertEqual(redacted["enabled"], "True")

    def test_settings_reject_negative_record_cap(self) -> None:
        with self.assertRaises(ValueError):
            TdxOfflineSettings(record_cap=-1)


class SuccessPathTest(unittest.TestCase):
    """A valid ``.day`` file produces a SUCCEEDED evidence tuple."""

    def setUp(self) -> None:
        self._tmp = Path(self._testMethodName)
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._payload = _build_record(
            20230103, 1234, 1300, 1200, 1275, 987654.5, 100000
        ) + _build_record(20230104, 1280, 1310, 1270, 1290, 1234567.25, 150000)
        _write_symbol_file(self._tmp, "sh", "600000", self._payload)
        self._settings = TdxOfflineSettings(enabled=True, data_root=self._tmp)
        self._provider = TdxOfflineStockProvider(
            self._settings, symbols=["600000"], clock=_fixed_clock
        )

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_fetch_daily_bars_returns_succeeded_evidence_tuple(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertEqual(request.provider_key, "tdx_offline")
        self.assertEqual(request.dataset_key, "stock_daily_bars")
        self.assertEqual(
            request.request_key,
            "daily-bars-2023-01-01-2023-12-31-600000",
        )
        self.assertEqual(
            request.params,
            {
                "symbols": ["600000"],
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
            },
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNone(attempt.error_code)
        self.assertIs(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        self.assertEqual(batch.warnings, ())
        self.assertTrue(batch.raw_payload_hash)

    def test_records_preserve_decimal_prices_and_amount(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertEqual(batch.records[0].trade_date, date(2023, 1, 3))
        self.assertEqual(batch.records[0].open, Decimal("12.34"))
        self.assertEqual(batch.records[0].high, Decimal("13.00"))
        self.assertEqual(batch.records[0].low, Decimal("12.00"))
        self.assertEqual(batch.records[0].close, Decimal("12.75"))
        self.assertEqual(batch.records[0].amount, Decimal("987654.5"))
        self.assertEqual(batch.records[1].trade_date, date(2023, 1, 4))
        self.assertEqual(batch.records[1].close, Decimal("12.90"))
        self.assertEqual(batch.records[1].amount, Decimal("1234567.25"))

    def test_bar_source_stamps_tdx_offline_provider_key(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        source_batch_ids = {bar.source.source_batch_id for bar in batch.records}
        # Every bar in the same batch must share the same
        # ``source_batch_id`` so the audit trail can be correlated
        # by batch.
        self.assertEqual(len(source_batch_ids), 1)
        for bar in batch.records:
            self.assertEqual(bar.source.provider_key, "tdx_offline")
            self.assertEqual(bar.source.observed_at, _FIXED_OBSERVED_AT)
            # The audit ``source_batch_id`` must be a UUID (the
            # Tushare adapter stamps the same shape) and must not
            # be the all-zero placeholder.
            from uuid import UUID

            UUID(str(bar.source.source_batch_id))

    def test_reverse_lookup_resolves_placeholder_to_symbol_exchange(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        sample = batch.records[0]
        self.assertEqual(
            self._provider.symbol_and_exchange_for_instrument_id(sample.instrument_id),
            ("600000", "SSE"),
        )

    def test_reverse_lookup_returns_none_for_unknown_id(self) -> None:
        from invest_domain.instruments.models import InstrumentId

        self.assertIsNone(
            self._provider.symbol_and_exchange_for_instrument_id(InstrumentId.generate())
        )

    def test_by_date_request_key_is_partition_aligned(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars_by_trade_date(date(2023, 1, 3))
        self.assertEqual(request.provider_key, "tdx_offline")
        self.assertEqual(request.dataset_key, "stock_daily_bars")
        self.assertEqual(request.request_key, "daily-bars-by-date-2023-01-03")
        self.assertEqual(request.params, {"trade_date": "2023-01-03"})
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 1)
        self.assertEqual(batch.records[0].trade_date, date(2023, 1, 3))

    def test_by_date_filters_to_the_requested_trade_date(self) -> None:
        # Trade date outside the file's date range must produce an
        # empty batch (the by-date path is the slice's primary
        # use-case so the filter is pinned here).
        request, attempt, batch = self._provider.fetch_daily_bars_by_trade_date(date(2023, 6, 1))
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNone(batch)

    def test_register_symbol_returns_placeholder(self) -> None:
        placeholder = self._provider.register_symbol("000001")
        resolved = self._provider.symbol_and_exchange_for_instrument_id(placeholder)
        self.assertEqual(resolved, ("000001", "SZSE"))

    def test_register_symbol_idempotent(self) -> None:
        first = self._provider.register_symbol("000001")
        second = self._provider.register_symbol("000001")
        self.assertEqual(first, second)


class MissingAndInvalidFileTest(unittest.TestCase):
    """Missing / invalid ``.day`` files fail closed with typed error codes."""

    def setUp(self) -> None:
        self._tmp = Path(self._testMethodName)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _settings(self) -> TdxOfflineSettings:
        return TdxOfflineSettings(enabled=True, data_root=self._tmp)

    def test_missing_file_fails_closed(self) -> None:
        provider = TdxOfflineStockProvider(self._settings(), symbols=["600000"], clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertIs(attempt.error_stage, ProviderFailureStage.STORAGE)
        self.assertEqual(attempt.error_code, "tdx_file_missing")
        self.assertIn("600000", attempt.error_message)
        self.assertIsNone(batch)

    def test_missing_file_by_date_fails_closed(self) -> None:
        provider = TdxOfflineStockProvider(self._settings(), symbols=["600000"], clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars_by_trade_date(date(2023, 1, 3))
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertIs(attempt.error_stage, ProviderFailureStage.STORAGE)
        self.assertEqual(attempt.error_code, "tdx_file_missing")
        self.assertIsNone(batch)

    def test_invalid_calendar_date_fails_closed(self) -> None:
        bad = _build_record(20230230, 1000, 1100, 950, 1050, 1.0, 100)
        _write_symbol_file(self._tmp, "sh", "600000", bad)
        provider = TdxOfflineStockProvider(self._settings(), symbols=["600000"], clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertIs(attempt.error_stage, ProviderFailureStage.STORAGE)
        self.assertEqual(attempt.error_code, "tdx_invalid_date")
        self.assertIsNone(batch)

    def test_invalid_size_fails_closed(self) -> None:
        payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        payload = payload[:-1]
        _write_symbol_file(self._tmp, "sh", "600000", payload)
        provider = TdxOfflineStockProvider(self._settings(), symbols=["600000"], clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_invalid_size")
        self.assertIsNone(batch)

    def test_partial_failure_records_first_error_and_drops_batch(self) -> None:
        # One symbol is valid, one is missing — the missing one
        # wins the error attribution; the whole attempt fails so
        # the application service can rerun the whole window
        # without a partial commit.
        good = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        _write_symbol_file(self._tmp, "sh", "600000", good)
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000", "000001"], clock=_fixed_clock
        )
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000", "000001"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_file_missing")
        self.assertIsNone(batch)


class DisabledAndNoUniverseTest(unittest.TestCase):
    """The provider refuses to fetch when ``enabled=False`` or no symbols are registered."""

    def setUp(self) -> None:
        self._tmp = Path(self._testMethodName)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_disabled_provider_returns_failed_attempt(self) -> None:
        settings = TdxOfflineSettings(enabled=False, data_root=self._tmp)
        provider = TdxOfflineStockProvider(settings, symbols=["600000"], clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_disabled")
        self.assertIs(attempt.error_stage, ProviderFailureStage.STORAGE)
        self.assertIsNone(batch)

    def test_by_date_without_universe_fails_closed(self) -> None:
        # Documented blocker: the by-date path needs a registered
        # universe so it knows which ``.day`` files to read; the
        # provider surfaces ``tdx_no_universe`` rather than silently
        # coercing the response.
        settings = TdxOfflineSettings(enabled=True, data_root=self._tmp)
        provider = TdxOfflineStockProvider(settings, clock=_fixed_clock)
        request, attempt, batch = provider.fetch_daily_bars_by_trade_date(date(2023, 1, 3))
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_no_universe")
        self.assertIsNone(batch)

    def test_record_cap_short_circuits_run(self) -> None:
        # The cap is operator-configurable; a single fetch that
        # would otherwise flood the sidecar must surface as a
        # typed failure so the application service can split the
        # window.
        good = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        _write_symbol_file(self._tmp, "sh", "600000", good)
        _write_symbol_file(self._tmp, "sz", "000001", good)
        settings = TdxOfflineSettings(enabled=True, data_root=self._tmp, record_cap=1)
        provider = TdxOfflineStockProvider(
            settings, symbols=["600000", "000001"], clock=_fixed_clock
        )
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000", "000001"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_record_cap_exceeded")
        self.assertIsNone(batch)


class PrimaryProviderPreservationTest(unittest.TestCase):
    """The catalog keeps the Tushare primary; TDX_OFFLINE is catalog-only and disabled."""

    def test_tushare_is_runtime_supported(self) -> None:
        # Tushare remains the only stock-data runtime provider.
        self.assertIn("tushare", runtime_supported_provider_keys())
        self.assertTrue(TUSHARE.has_runtime_factory_adapter)
        self.assertTrue(TUSHARE.capabilities)
        self.assertIn("stock_daily_bars", {cap.value for cap in TUSHARE.capabilities})

    def test_tdx_offline_is_catalog_only(self) -> None:
        # TDX_OFFLINE is the same shape as HITHINK: catalog-only,
        # disabled by default, no runtime factory adapter so a
        # future regression cannot silently re-introduce it into
        # the runtime surface.
        self.assertIs(TDX_OFFLINE.provider_key, "tdx_offline")
        self.assertEqual({cap.value for cap in TDX_OFFLINE.capabilities}, {"stock_daily_bars"})
        self.assertFalse(TDX_OFFLINE.enabled_by_default)
        self.assertFalse(TDX_OFFLINE.has_runtime_factory_adapter)
        self.assertNotIn("tdx_offline", runtime_supported_provider_keys())

    def test_tdx_offline_is_visible_via_lookup_and_iter(self) -> None:
        self.assertIs(lookup_provider("tdx_offline"), TDX_OFFLINE)
        iterated = {d.provider_key for d in iter_provider_declarations()}
        self.assertIn("tdx_offline", iterated)

    def test_fixture_dev_default_unchanged(self) -> None:
        # The slice does not change which provider is on by
        # default — the offline adapter stays opt-in so the
        # primary Tushare / fixture path cannot be silently
        # replaced.
        self.assertTrue(FIXTURE_DEV.enabled_by_default)
        self.assertFalse(TDX_OFFLINE.enabled_by_default)
        self.assertFalse(HITHINK.enabled_by_default)


class ApplicationServiceCompatibilityTest(unittest.TestCase):
    """The provider plugs into ``write_stock_daily_bars_raw`` without contract changes."""

    def setUp(self) -> None:
        from invest_storage.models import (
            ProviderAttemptRow,
            ProviderRequestRow,
        )
        from invest_storage.repositories import (
            NewProviderRequest,
            SqlAlchemyProviderAttemptRepository,
            SqlAlchemyProviderBatchRepository,
            SqlAlchemyProviderRequestRepository,
        )
        from sqlalchemy.orm import Session

        self._tmp = Path("test_app_service_compat")
        self._tmp.mkdir(parents=True, exist_ok=True)
        good = _build_record(20230103, 1234, 1300, 1200, 1275, 987654.5, 100000) + _build_record(
            20230104, 1280, 1310, 1270, 1290, 1234567.25, 150000
        )
        _write_symbol_file(self._tmp, "sh", "600000", good)
        self._settings = TdxOfflineSettings(enabled=True, data_root=self._tmp)
        self._provider = TdxOfflineStockProvider(
            self._settings, symbols=["600000"], clock=_fixed_clock
        )

        self._session = MagicMock(name="Session", spec=Session)
        self._session.added_rows = []
        self._session.flush.return_value = None
        self._session.commit.return_value = None
        self._session.rollback.return_value = None
        self._session.close.return_value = None

        def _add(row: Any) -> None:
            self._session.added_rows.append(row)

        self._session.add.side_effect = _add

        def _get(_model: Any, primary_key: Any) -> Any:
            for row in self._session.added_rows:
                if getattr(row, "id", None) == primary_key:
                    return row
            return None

        self._session.get.side_effect = _get

        self._request_log: list[ProviderRequestRow] = []

        def _get_or_create(request: NewProviderRequest) -> Any:
            for row in self._request_log:
                if (
                    row.provider_key == request.provider_key
                    and row.dataset_key == request.dataset_key
                    and row.request_key == request.request_key
                ):
                    return row
            from uuid import uuid4

            row = ProviderRequestRow(
                id=uuid4(),
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                request_params=dict(request.request_params),
                requested_by_run_id=request.requested_by_run_id,
                status=request.status,
            )
            self._session.add(row)
            self._request_log.append(row)
            return row

        def _list_by_request(request_id: Any, *, limit: int = 100, offset: int = 0) -> list[Any]:
            matched = sorted(
                (
                    r
                    for r in self._session.added_rows
                    if isinstance(r, ProviderAttemptRow) and r.provider_request_id == request_id
                ),
                key=lambda r: r.attempt_no,
            )
            return matched[offset : offset + limit]

        self._provider_request_repo = SqlAlchemyProviderRequestRepository(self._session)
        self._provider_request_repo.get_or_create = _get_or_create  # type: ignore[method-assign]
        self._provider_attempt_repo = SqlAlchemyProviderAttemptRepository(self._session)
        self._provider_attempt_repo.list_by_request = _list_by_request  # type: ignore[method-assign]
        self._provider_batch_repo = SqlAlchemyProviderBatchRepository(self._session)

        self._fake_uow = MagicMock(name="UoW")
        self._fake_uow.__enter__ = MagicMock(return_value=self._fake_uow)
        self._fake_uow.__exit__ = MagicMock(return_value=False)
        self._fake_uow.provider_requests = self._provider_request_repo
        self._fake_uow.provider_attempts = self._provider_attempt_repo
        self._fake_uow.provider_batches = self._provider_batch_repo

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _uow_factory(self) -> MagicMock:
        def _factory(*_args: Any, **_kwargs: Any) -> Any:
            return self._fake_uow

        return MagicMock(name="UoWFactory", side_effect=_factory)

    def test_provider_fits_write_stock_daily_bars_raw(self) -> None:
        from invest_pipeline.stock_daily_bars import write_stock_daily_bars_raw

        result = write_stock_daily_bars_raw(
            self._provider,
            MagicMock(return_value=self._session),
            symbols=["600000"],
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            unit_of_work_factory=self._uow_factory(),
        )
        self.assertEqual(result.request_status, "succeeded")
        self.assertEqual(result.attempt_status, "succeeded")
        self.assertEqual(result.record_count, 2)
        self.assertIsNotNone(result.batch_id)

    def test_sidecar_carries_tdx_offline_provider_key(self) -> None:
        from invest_pipeline.stock_daily_bars import write_stock_daily_bars_raw
        from invest_storage.models import ProviderAttemptRow

        write_stock_daily_bars_raw(
            self._provider,
            MagicMock(return_value=self._session),
            symbols=["600000"],
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            unit_of_work_factory=self._uow_factory(),
        )
        attempts = [r for r in self._session.added_rows if isinstance(r, ProviderAttemptRow)]
        self.assertEqual(len(attempts), 1)
        payload = json.loads(str(attempts[0].response_payload_json))
        self.assertEqual(
            [record["source_provider"] for record in payload["records"]],
            ["tdx_offline", "tdx_offline"],
        )
        self.assertEqual(
            [record["exchange"] for record in payload["records"]],
            ["SSE", "SSE"],
        )
        self.assertEqual(
            [record["symbol"] for record in payload["records"]],
            ["600000", "600000"],
        )


class Phase1AQualifiedPairsTest(unittest.TestCase):
    """Phase 1A (TDX production fallback) market-qualified pair path.

    The Phase 1A slice widens the adapter so Beijing (``bj``)
    symbols can be read alongside Shanghai (``sh``) and Shenzhen
    (``sz``) without breaking the existing
    :meth:`register_symbol` / :meth:`fetch_daily_bars` callers. The
    new entry points — :meth:`register_pair`,
    :meth:`discover_symbols` and :meth:`fetch_daily_bars_by_pairs` —
    accept an explicit ``(market, symbol)`` pair so a caller can opt
    out of the prefix-based heuristic.
    """

    def setUp(self) -> None:
        self._tmp = Path(self._testMethodName)
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._settings = TdxOfflineSettings(enabled=True, data_root=self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_register_pair_bj_returns_bjse_placeholder(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        placeholder = provider.register_pair("bj", "110001")
        resolved = provider.symbol_and_exchange_for_instrument_id(placeholder)
        self.assertEqual(resolved, ("110001", "BJSE"))

    def test_register_pair_idempotent(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        first = provider.register_pair("bj", "110001")
        second = provider.register_pair("bj", "110001")
        self.assertEqual(first, second)

    def test_register_pair_rejects_unknown_market(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        from invest_pipeline.adapters.tdx_offline import TdxInvalidMarketError

        with self.assertRaises(TdxInvalidMarketError):
            provider.register_pair("us", "110001")

    def test_register_pair_rejects_invalid_symbol(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        from invest_pipeline.adapters.tdx_offline import TdxInvalidSymbolError

        with self.assertRaises(TdxInvalidSymbolError):
            provider.register_pair("bj", "12345")

    def test_discover_symbols_returns_pairs_for_populated_tree(self) -> None:
        payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        _write_symbol_file(self._tmp, "sh", "600000", payload)
        _write_symbol_file(self._tmp, "sz", "000001", payload)
        _write_symbol_file(self._tmp, "bj", "110001", payload)

        provider = TdxOfflineStockProvider(self._settings)
        pairs = provider.discover_symbols()

        self.assertEqual(
            pairs,
            (
                ("bj", "110001"),
                ("sh", "600000"),
                ("sz", "000001"),
            ),
        )

    def test_discover_symbols_handles_empty_tree(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        self.assertEqual(provider.discover_symbols(), ())

    def test_discover_symbols_handles_missing_data_root(self) -> None:
        # ``discover_symbols`` is a pure filesystem scan over the
        # configured ``data_root``; it never raises on a missing
        # root so the by-date fallback can rely on a successful
        # call to a non-existent tree.
        settings = TdxOfflineSettings(
            enabled=True, data_root=self._tmp / "does_not_exist"
        )
        provider = TdxOfflineStockProvider(settings)
        self.assertEqual(provider.discover_symbols(), ())

    def test_discover_symbols_works_when_disabled(self) -> None:
        # The discovery primitive is metadata-only; it does not
        # consult the ``enabled`` flag so a follow-up asset can
        # build the universe before flipping the provider on.
        settings = TdxOfflineSettings(enabled=False, data_root=self._tmp)
        _write_symbol_file(self._tmp, "bj", "110001", b"")
        provider = TdxOfflineStockProvider(settings)
        self.assertEqual(provider.discover_symbols(), (("bj", "110001"),))

    def test_fetch_daily_bars_by_pairs_bj(self) -> None:
        payload = _build_record(20230103, 1500, 1600, 1450, 1550, 100.0, 1000)
        _write_symbol_file(self._tmp, "bj", "110001", payload)

        provider = TdxOfflineStockProvider(self._settings)
        request, attempt, batch = provider.fetch_daily_bars_by_pairs(
            [("bj", "110001")], date(2023, 1, 1), date(2023, 12, 31)
        )

        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(request.request_key, "daily-bars-by-pairs-2023-01-01-2023-12-31-bj110001")
        self.assertEqual(request.params["pairs"], [["bj", "110001"]])
        self.assertEqual(len(batch.records), 1)
        self.assertEqual(batch.records[0].trade_date, date(2023, 1, 3))
        self.assertEqual(batch.records[0].close, Decimal("15.50"))
        # The market-qualified path must stamp the canonical
        # exchange identifier on every record so the upstream
        # service can route the offline evidence to the
        # ``core.instruments`` / ``core.daily_bars`` partition.
        self.assertEqual(
            provider.symbol_and_exchange_for_instrument_id(
                batch.records[0].instrument_id
            ),
            ("110001", "BJSE"),
        )

    def test_fetch_daily_bars_by_pairs_supports_multiple_markets(self) -> None:
        sh_payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        sz_payload = _build_record(20230104, 2000, 2100, 1950, 2050, 2.0, 200)
        bj_payload = _build_record(20230105, 3000, 3100, 2950, 3050, 3.0, 300)
        _write_symbol_file(self._tmp, "sh", "600000", sh_payload)
        _write_symbol_file(self._tmp, "sz", "000001", sz_payload)
        _write_symbol_file(self._tmp, "bj", "110001", bj_payload)

        provider = TdxOfflineStockProvider(self._settings)
        request, attempt, batch = provider.fetch_daily_bars_by_pairs(
            [("sh", "600000"), ("sz", "000001"), ("bj", "110001")],
            date(2023, 1, 1),
            date(2023, 12, 31),
        )

        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(
            sorted(record.trade_date for record in batch.records),
            [date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)],
        )
        # The request key is sorted by ``(market, symbol)`` so two
        # callers passing the same set of pairs in different
        # orders collide on the same ``raw.provider_requests`` row.
        self.assertEqual(
            request.request_key,
            "daily-bars-by-pairs-2023-01-01-2023-12-31-bj110001-sh600000-sz000001",
        )

    def test_fetch_daily_bars_by_pairs_fails_closed_on_missing_file(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        request, attempt, batch = provider.fetch_daily_bars_by_pairs(
            [("bj", "999999")], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_code, "tdx_file_missing")
        self.assertIsNone(batch)

    def test_fetch_daily_bars_by_pairs_rejects_empty_pairs(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        with self.assertRaises(ValueError):
            provider.fetch_daily_bars_by_pairs(
                [], date(2023, 1, 1), date(2023, 12, 31)
            )

    def test_fetch_daily_bars_by_pairs_rejects_inverted_dates(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        with self.assertRaises(ValueError):
            provider.fetch_daily_bars_by_pairs(
                [("bj", "110001")], date(2023, 12, 31), date(2023, 1, 1)
            )

    def test_fetch_daily_bars_by_pairs_rejects_unknown_market(self) -> None:
        provider = TdxOfflineStockProvider(self._settings)
        from invest_pipeline.adapters.tdx_offline import TdxInvalidMarketError

        with self.assertRaises(TdxInvalidMarketError):
            provider.fetch_daily_bars_by_pairs(
                [("us", "110001")], date(2023, 1, 1), date(2023, 12, 31)
            )

    def test_existing_sh_sz_callers_continue_to_work(self) -> None:
        # The Phase 1A slice must not break the existing SH/SZ
        # contract: a caller that registers and fetches plain
        # symbols still gets the same prefix-based routing and the
        # same ``SSE`` / ``SZSE`` exchange stamp on the sidecar.
        sh_payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
        sz_payload = _build_record(20230104, 2000, 2100, 1950, 2050, 2.0, 200)
        _write_symbol_file(self._tmp, "sh", "600000", sh_payload)
        _write_symbol_file(self._tmp, "sz", "000001", sz_payload)

        provider = TdxOfflineStockProvider(
            self._settings, symbols=["600000", "000001"]
        )
        request, attempt, batch = provider.fetch_daily_bars(
            ["600000", "000001"], date(2023, 1, 1), date(2023, 12, 31)
        )

        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        # The audit ``exchange`` stamp is the canonical
        # identifier; the prefix-based heuristic still resolves
        # ``600000`` to ``SSE`` and ``000001`` to ``SZSE``.
        exchanges = {
            provider.symbol_and_exchange_for_instrument_id(
                record.instrument_id
            )
            for record in batch.records
        }
        self.assertEqual(exchanges, {("600000", "SSE"), ("000001", "SZSE")})
        # The request key is the slice-1 contract and must remain
        # unchanged for downstream consumers that correlate audit
        # rows by ``request_key``.
        self.assertEqual(
            request.request_key, "daily-bars-2023-01-01-2023-12-31-000001-600000"
        )


class PrevCloseChainTest(unittest.TestCase):
    """Per-symbol ``prev_close`` chain: first ``None``, later carry prior close.

    The TDX offline mapping has no per-bar prev_close field on disk,
    so the adapter walks each symbol/file sequence as returned by the
    reader and stamps the prior record's close onto the next one.
    The state is per-symbol/file — the chain restarts at ``None``
    for every distinct symbol even when several are read in the
    same run — and the reader is the source of truth for ordering,
    so the chain inherits whatever duplicate / out-of-order / invalid
    / empty / single / error behaviour the reader already exposes.
    """

    def setUp(self) -> None:
        self._tmp = Path(self._testMethodName)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _settings(self) -> TdxOfflineSettings:
        return TdxOfflineSettings(enabled=True, data_root=self._tmp)

    def test_single_record_has_prev_close_none(self) -> None:
        # A one-bar file produces exactly one record whose
        # ``prev_close`` is ``None`` — the chain has no prior bar to
        # borrow from, and there is no fallback to a synthetic
        # previous close.
        _write_symbol_file(
            self._tmp,
            "sh",
            "600000",
            _build_record(20230103, 1234, 1300, 1200, 1275, 100.0, 1000),
        )
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000"], clock=_fixed_clock
        )
        _, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 1)
        self.assertIsNone(batch.records[0].prev_close)
        self.assertEqual(batch.records[0].close, Decimal("12.75"))

    def test_first_record_prev_close_is_none(self) -> None:
        # Multi-day chain, asserted head: the first record carries
        # ``prev_close=None`` regardless of how many follow.
        payload = (
            _build_record(20230103, 1234, 1300, 1200, 1275, 100.0, 1000)
            + _build_record(20230104, 1280, 1310, 1270, 1290, 200.0, 2000)
        )
        _write_symbol_file(self._tmp, "sh", "600000", payload)
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000"], clock=_fixed_clock
        )
        _, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 2)
        self.assertIsNone(batch.records[0].prev_close)

    def test_multi_day_chain_carries_previous_close(self) -> None:
        # Multi-day chain, asserted tail: each later record carries
        # the immediately preceding record's close, walked in the
        # reader's return order. No sort, no filter, no
        # synthetic-prev fallback.
        payload = (
            _build_record(20230103, 1234, 1300, 1200, 1275, 100.0, 1000)
            + _build_record(20230104, 1280, 1310, 1270, 1290, 200.0, 2000)
            + _build_record(20230105, 1290, 1320, 1280, 1305, 300.0, 3000)
        )
        _write_symbol_file(self._tmp, "sh", "600000", payload)
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000"], clock=_fixed_clock
        )
        _, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 3)
        self.assertIsNone(batch.records[0].prev_close)
        self.assertEqual(batch.records[1].prev_close, batch.records[0].close)
        self.assertEqual(batch.records[2].prev_close, batch.records[1].close)
        self.assertEqual(
            [str(bar.prev_close) for bar in batch.records],
            ["None", "12.75", "12.9"],
        )

    def test_empty_file_produces_no_records(self) -> None:
        # An empty ``.day`` file yields an empty reader tuple, which
        # in turn yields no ``DailyBar`` records. The empty path is
        # preserved — neither the chain state nor the empty attempt
        # contract change.
        _write_symbol_file(self._tmp, "sh", "600000", b"")
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000"], clock=_fixed_clock
        )
        _, attempt, batch = provider.fetch_daily_bars(
            ["600000"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNone(batch)

    def test_state_is_isolated_per_symbol(self) -> None:
        # The chain must restart at ``None`` for each distinct
        # symbol/file — the previous close of one symbol must not
        # bleed into the chain of another. The reader returns the
        # symbols in the order they are read; the adapter walks
        # each sequence independently.
        sh_payload = (
            _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
            + _build_record(20230104, 1060, 1110, 1040, 1090, 2.0, 200)
            + _build_record(20230105, 1090, 1140, 1080, 1120, 3.0, 300)
        )
        sz_payload = (
            _build_record(20230103, 2000, 2100, 1950, 2050, 4.0, 400)
            + _build_record(20230104, 2060, 2110, 2040, 2090, 5.0, 500)
        )
        _write_symbol_file(self._tmp, "sh", "600000", sh_payload)
        _write_symbol_file(self._tmp, "sz", "000001", sz_payload)
        provider = TdxOfflineStockProvider(
            self._settings(), symbols=["600000", "000001"], clock=_fixed_clock
        )
        _, attempt, batch = provider.fetch_daily_bars(
            ["600000", "000001"], date(2023, 1, 1), date(2023, 12, 31)
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 5)
        # Group by exchange so the per-symbol chain assertions are
        # robust against iteration order over the dict.
        by_exchange: dict[str, list[Any]] = {}
        for record in batch.records:
            resolved = provider.symbol_and_exchange_for_instrument_id(
                record.instrument_id
            )
            by_exchange.setdefault(resolved[1], []).append(record)
        self.assertEqual(set(by_exchange), {"SSE", "SZSE"})
        self.assertEqual(len(by_exchange["SSE"]), 3)
        self.assertEqual(len(by_exchange["SZSE"]), 2)
        # Each symbol's chain starts at ``None`` — the last close
        # of the other symbol is never reused.
        for chain in by_exchange.values():
            self.assertIsNone(chain[0].prev_close)
        # Each subsequent bar in a chain carries the prior close of
        # the same chain.
        for chain in by_exchange.values():
            for previous, current in zip(chain, chain[1:]):
                self.assertEqual(current.prev_close, previous.close)

    def test_chain_works_for_by_pairs_path(self) -> None:
        # The market-qualified pair path goes through
        # ``_fetch_by_pairs``; the chain semantics must be identical
        # so the by-pairs fallback cannot drift from the per-symbol
        # one.
        sh_payload = (
            _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
            + _build_record(20230104, 1060, 1110, 1040, 1090, 2.0, 200)
        )
        bj_payload = (
            _build_record(20230105, 1500, 1600, 1450, 1550, 3.0, 300)
            + _build_record(20230106, 1560, 1610, 1540, 1590, 4.0, 400)
            + _build_record(20230107, 1590, 1640, 1580, 1620, 5.0, 500)
        )
        _write_symbol_file(self._tmp, "sh", "600000", sh_payload)
        _write_symbol_file(self._tmp, "bj", "110001", bj_payload)
        provider = TdxOfflineStockProvider(self._settings())
        _, attempt, batch = provider.fetch_daily_bars_by_pairs(
            [("sh", "600000"), ("bj", "110001")],
            date(2023, 1, 1),
            date(2023, 12, 31),
        )
        self.assertIs(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), 5)
        by_exchange: dict[str, list[Any]] = {}
        for record in batch.records:
            resolved = provider.symbol_and_exchange_for_instrument_id(
                record.instrument_id
            )
            by_exchange.setdefault(resolved[1], []).append(record)
        self.assertEqual(set(by_exchange), {"SSE", "BJSE"})
        for chain in by_exchange.values():
            self.assertIsNone(chain[0].prev_close)
            for previous, current in zip(chain, chain[1:]):
                self.assertEqual(current.prev_close, previous.close)


if __name__ == "__main__":
    unittest.main()
