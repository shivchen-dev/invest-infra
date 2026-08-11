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

Slice 1 deliberately does **not** wire the runtime fallback into
the ``stock_daily_bars_raw`` Dagster asset — the asset-level
fallback orchestration is a follow-up that requires a
symbol-enumeration contract the slice does not invent.
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


if __name__ == "__main__":
    unittest.main()
