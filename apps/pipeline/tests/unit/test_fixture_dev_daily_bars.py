"""Unit tests for the PR-06 fixture_dev daily-bars adapter.

The adapter's three-layer evidence model for daily bars — a
``(ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None)``
triple — is the contract exercised here. Both the success path and
the ``simulate_failure`` branch must produce well-formed domain
objects that the storage repositories can persist without violating
the ``raw.provider_attempts`` CHECK constraints, plus a deterministic
JSONB sidecar the downstream ``etf_daily_bars`` service can re-read
without re-calling the Provider.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date, datetime
from decimal import Decimal

from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
    ProviderFailureStage,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_pipeline.adapters.fixture_dev.adapter import (
    _DAILY_BARS_FIXTURE_PATH,
    _DAILY_BARS_SCHEMA_VERSION,
    FixtureDevInstrumentProvider,
    deserialize_daily_bars,
    serialize_daily_bars,
)


class FixtureDevDailyBarsFixtureTest(unittest.TestCase):
    """On-disk fixture invariants (path, schema_version, content)."""

    def test_fixture_path_resolves_alongside_adapter(self) -> None:
        self.assertTrue(
            _DAILY_BARS_FIXTURE_PATH.exists(),
            f"missing {_DAILY_BARS_FIXTURE_PATH}",
        )
        self.assertEqual(_DAILY_BARS_FIXTURE_PATH.parent.name, "fixture_dev")

    def test_fixture_has_at_least_five_days_per_symbol(self) -> None:
        provider = FixtureDevInstrumentProvider()
        records = provider.list_daily_bars_records()
        by_symbol: dict[str, list[dict[str, object]]] = {}
        for record in records:
            by_symbol.setdefault(str(record["symbol"]), []).append(record)
        # 12 ETFs (the full PR-04 universe) are in scope.
        self.assertGreaterEqual(
            len(by_symbol), 12, f"expected >=12 symbols, got {sorted(by_symbol)}"
        )
        for symbol, rows in by_symbol.items():
            self.assertGreaterEqual(
                len(rows),
                5,
                f"symbol {symbol!r} has only {len(rows)} days; spec requires 5-10",
            )

    def test_fixture_ohlc_invariants(self) -> None:
        """Every record's OHLC must satisfy ADR-0005 row invariants."""

        for record in FixtureDevInstrumentProvider().list_daily_bars_records():
            o = Decimal(record["open"])
            h = Decimal(record["high"])
            low = Decimal(record["low"])
            c = Decimal(record["close"])
            self.assertGreater(o, 0)
            self.assertGreater(h, 0)
            self.assertGreater(low, 0)
            self.assertGreater(c, 0)
            self.assertGreaterEqual(
                h,
                max(o, c, low),
                f"high {h} < max(open, close, low)={max(o, c, low)} "
                f"for {record['symbol']} {record['trade_date']}",
            )
            self.assertLessEqual(
                low,
                min(o, c, h),
                f"low {low} > min(open, close, high)={min(o, c, h)} "
                f"for {record['symbol']} {record['trade_date']}",
            )
            self.assertEqual(record["trading_status"], "normal")


class FixtureDevDailyBarsFetchTest(unittest.TestCase):
    """End-to-end coverage of :meth:`FixtureDevInstrumentProvider.fetch_daily_bars`."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()

    def test_provider_key_is_fixture_dev(self) -> None:
        self.assertEqual(self._provider.provider_key, "fixture_dev")

    def test_fetch_daily_bars_filters_by_symbols_and_date_range(self) -> None:
        symbols = ["510300", "510500"]
        start = date(2026, 7, 24)
        end = date(2026, 7, 28)
        request, attempt, batch = self._provider.fetch_daily_bars(
            symbols, start, end
        )

        # --- ProviderRequest ---
        self.assertEqual(request.provider_key, "fixture_dev")
        self.assertEqual(request.dataset_key, "etf_daily_bars")
        self.assertEqual(
            request.request_key,
            f"daily-bars-{start.isoformat()}-{end.isoformat()}-510300-510500",
        )
        self.assertEqual(
            request.params,
            {
                "symbols": ["510300", "510500"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        self.assertIsInstance(request.created_at, datetime)
        self.assertIsNotNone(request.created_at.tzinfo)

        # --- ProviderAttempt ---
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.finished_at)

        # --- ProviderBatch ---
        assert batch is not None
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(batch.warnings, ())
        # 2 symbols x 3 trading days (2026-07-24 / 2026-07-27 / 2026-07-28)
        self.assertEqual(len(batch.records), 6)
        seen_dates = sorted({b.trade_date for b in batch.records})
        self.assertEqual(
            seen_dates,
            [date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28)],
        )
        # Each symbol should have a distinct placeholder UUID
        seen_ids = {b.instrument_id for b in batch.records}
        self.assertEqual(
            len(seen_ids), 2, "expected one placeholder UUID per symbol"
        )

        # All records must be valid DailyBar instances
        for bar in batch.records:
            self.assertEqual(bar.adjustment, Adjust.NONE)
            self.assertEqual(bar.trading_status, TradingStatus.NORMAL)
            self.assertEqual(bar.revision, 1)
            self.assertIsNotNone(bar.row_hash)
            # BarSource.observed_at must be timezone-aware
            self.assertIsNotNone(bar.source.observed_at.tzinfo)
            # source_batch_id must be a UUID (not None) per ADR-0005 §3
            self.assertIsNotNone(bar.source.source_batch_id)

    def test_fetch_daily_bars_returns_empty_batch_for_unknown_symbol(self) -> None:
        request, attempt, batch = self._provider.fetch_daily_bars(
            ["000000"], date(2026, 7, 23), date(2026, 7, 30)
        )
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        assert batch is not None
        self.assertEqual(batch.records, ())
        # raw_payload_hash is the SHA-256 of an empty records list
        self.assertEqual(
            batch.raw_payload_hash,
            hashlib.sha256(json.dumps([], separators=(",", ":")).encode("utf-8")).hexdigest(),
        )
        # request_key still carries the symbol even with no hits
        self.assertIn("000000", request.request_key)

    def test_fetch_daily_bars_rejects_inverted_range(self) -> None:
        with self.assertRaises(ValueError):
            self._provider.fetch_daily_bars(
                ["510300"], date(2026, 7, 30), date(2026, 7, 23)
            )

    def test_fetch_daily_bars_failure_bundle_has_no_batch(self) -> None:
        provider = FixtureDevInstrumentProvider(simulate_failure=True)
        request, attempt, batch = provider.fetch_daily_bars(
            ["510300"], date(2026, 7, 23), date(2026, 7, 30)
        )
        self.assertIsNone(batch)
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_stage, ProviderFailureStage.PROVIDER)
        self.assertTrue(attempt.error_code)
        self.assertTrue(attempt.error_message)

    def test_placeholder_instrument_id_is_stable_per_symbol(self) -> None:
        first = self._provider.placeholder_instrument_id("510300")
        second = self._provider.placeholder_instrument_id("510300")
        self.assertEqual(first, second)
        self.assertIsNotNone(first)
        # Different symbols get different placeholders
        other = self._provider.placeholder_instrument_id("510500")
        self.assertNotEqual(first, other)


class FixtureDevDailyBarsSidecarTest(unittest.TestCase):
    """The JSONB sidecar must round-trip and carry the audit metadata."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()

    def _observed(self) -> datetime:
        return datetime.fromisoformat("2026-07-31T08:00:00+00:00")

    def _build_sidecar(
        self, records: list[dict[str, object]]
    ) -> str:
        return serialize_daily_bars(
            records,
            source_batch_id=__import__("uuid").uuid4(),
            observed_at=self._observed(),
        )

    def test_sidecar_round_trips(self) -> None:
        records = [
            {
                "symbol": "510300",
                "trade_date": "2026-07-23",
                "open": "3.835",
                "high": "3.845",
                "low": "3.817",
                "close": "3.827",
                "prev_close": "3.878",
                "volume": "11750000",
                "amount": "44967250.00",
                "trading_status": "normal",
            }
        ]
        payload = self._build_sidecar(records)
        round_tripped = deserialize_daily_bars(payload)
        self.assertEqual(len(round_tripped), 1)
        entry = round_tripped[0]
        self.assertEqual(entry["symbol"], "510300")
        self.assertEqual(entry["trade_date"], "2026-07-23")
        self.assertEqual(entry["trading_status"], "normal")
        self.assertEqual(entry["open"], "3.835")
        self.assertEqual(entry["source_provider"], "fixture_dev")
        self.assertEqual(entry["observed_at"], self._observed().isoformat())

    def test_sidecar_has_schema_version(self) -> None:
        records = [
            {
                "symbol": "510300",
                "trade_date": "2026-07-23",
                "open": "3.835",
                "high": "3.845",
                "low": "3.817",
                "close": "3.827",
                "prev_close": "3.878",
                "volume": "11750000",
                "amount": "44967250.00",
                "trading_status": "normal",
            }
        ]
        payload = self._build_sidecar(records)
        parsed = json.loads(payload)
        self.assertEqual(parsed["schema_version"], _DAILY_BARS_SCHEMA_VERSION)

    def test_deserialize_daily_bars_rejects_unsupported_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            deserialize_daily_bars('{"schema_version": 999, "records": []}')

    def test_deserialize_daily_bars_rejects_non_list_records(self) -> None:
        with self.assertRaises(ValueError):
            deserialize_daily_bars(
                f'{{"schema_version": {_DAILY_BARS_SCHEMA_VERSION}, "records": "nope"}}'
            )

    def test_deserialize_daily_bars_handles_none(self) -> None:
        self.assertEqual(deserialize_daily_bars(None), [])


if __name__ == "__main__":
    unittest.main()
