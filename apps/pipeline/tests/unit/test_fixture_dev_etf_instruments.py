"""Unit tests for the PR-05 fixture_dev ETF instrument adapter.

The adapter's three-layer evidence model — ``(ProviderRequest,
ProviderAttempt, ProviderBatch[Instrument] | None)`` — is the
contract exercised here. Both the success and the
``simulate_failure`` branches must produce well-formed domain objects
that the storage repositories can persist without violating the
``raw.provider_attempts`` CHECK constraints.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import date, datetime

from invest_domain.instruments import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
    ProviderFailureStage,
)
from invest_domain.shared.values import Currency, Exchange
from invest_pipeline.adapters.fixture_dev.adapter import (
    _FIXTURE_PATH,
    FixtureDevInstrumentProvider,
    deserialize_records,
)


class FixtureDevEtfInstrumentsTest(unittest.TestCase):
    """End-to-end coverage of the fixture_dev adapter's three-layer contract."""

    def setUp(self) -> None:
        self._provider = FixtureDevInstrumentProvider()

    def test_fixture_json_path_resolves_alongside_adapter(self) -> None:
        """The on-disk fixture must be co-located with the adapter module."""

        self.assertTrue(_FIXTURE_PATH.exists(), f"missing {_FIXTURE_PATH}")
        self.assertEqual(
            _FIXTURE_PATH.parent.name, "fixture_dev"
        )

    def test_fixture_loads_12_instruments(self) -> None:
        """The fixture must expose 12+ SSE / SZSE ETFs per the PR-05 spec."""

        instruments = self._provider.list_instruments()
        self.assertGreaterEqual(
            len(instruments), 10, "fixture must carry at least 10 ETFs"
        )
        for instrument in instruments:
            self.assertIsInstance(instrument, Instrument)
            self.assertIsInstance(instrument.symbol, str)
            self.assertTrue(instrument.symbol)
            self.assertIsInstance(instrument.name, str)
            self.assertTrue(instrument.name)
            self.assertIn(instrument.exchange, {e.value for e in Exchange})
            self.assertEqual(instrument.instrument_type, InstrumentType.ETF)
            self.assertIsInstance(instrument.list_date, date)
            self.assertEqual(instrument.status, InstrumentStatus.ACTIVE)

    def test_fixture_records_are_deterministic(self) -> None:
        """Re-instantiating the provider must return the same instruments."""

        other = FixtureDevInstrumentProvider()
        first = self._provider.list_instruments()
        second = other.list_instruments()
        self.assertEqual(len(first), len(second))
        for a, b in zip(first, second, strict=True):
            self.assertEqual(a.symbol, b.symbol)
            self.assertEqual(a.exchange, a.exchange)
            self.assertEqual(a.name, a.name)
            self.assertEqual(a.list_date, b.list_date)

    def test_provider_key_is_fixture_dev(self) -> None:
        self.assertEqual(self._provider.provider_key, "fixture_dev")

    def test_fetch_instruments_returns_three_layer_success_bundle(self) -> None:
        """The success path must return a fully-formed request / attempt / batch triple."""

        as_of = date(2026, 7, 31)
        request, attempt, batch = self._provider.fetch_instruments(as_of)

        # --- ProviderRequest ---
        self.assertEqual(request.provider_key, "fixture_dev")
        self.assertEqual(request.dataset_key, "etf_instruments")
        self.assertEqual(request.request_key, f"instruments-{as_of.isoformat()}")
        self.assertEqual(request.params, {"as_of": as_of.isoformat()})
        self.assertIsInstance(request.created_at, datetime)
        self.assertIsNotNone(request.created_at.tzinfo)

        # --- ProviderAttempt ---
        import uuid

        self.assertIsInstance(attempt.request_id, uuid.UUID)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.finished_at)
        self.assertGreaterEqual(attempt.duration_ms, 0)
        self.assertIsNone(attempt.error_stage)
        self.assertIsNone(attempt.error_code)

        # --- ProviderBatch ---
        self.assertIsNotNone(batch)
        assert batch is not None  # for type-checker
        self.assertEqual(batch.status, ProviderBatchStatus.SUCCEEDED)
        self.assertEqual(len(batch.records), len(self._provider.list_instruments()))
        self.assertEqual(batch.records, tuple(self._provider.list_instruments()))
        # raw_payload_hash is the SHA-256 of the on-disk JSON file
        expected_hash = hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest()
        self.assertEqual(batch.raw_payload_hash, expected_hash)
        self.assertEqual(batch.warnings, ())

    def test_fetch_instruments_records_carry_required_fields(self) -> None:
        """Every record must carry the fields the core.instruments table stores."""

        _, _, batch = self._provider.fetch_instruments(date(2026, 7, 31))
        assert batch is not None
        for instrument in batch.records:
            self.assertIsNone(instrument.instrument_id)  # fixture leaves it None
            self.assertEqual(instrument.currency, Currency.CNY)
            self.assertIn(instrument.exchange, {"SSE", "SZSE"})
            self.assertIsNotNone(instrument.list_date)
            self.assertEqual(instrument.status, InstrumentStatus.ACTIVE)
            # provider_symbol_map must round-trip fixture_dev's symbol
            self.assertEqual(
                instrument.provider_symbol_map.get("fixture_dev"), instrument.symbol
            )

    def test_fetch_instruments_failure_bundle_has_no_batch(self) -> None:
        """A failed attempt must carry error_stage / error_code and return batch=None."""

        provider = FixtureDevInstrumentProvider(simulate_failure=True)
        as_of = date(2026, 7, 31)
        request, attempt, batch = provider.fetch_instruments(as_of)

        self.assertIsNone(batch)
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        self.assertEqual(attempt.error_stage, ProviderFailureStage.PROVIDER)
        self.assertTrue(attempt.error_code)
        self.assertTrue(attempt.error_message)
        self.assertIsNotNone(attempt.finished_at)

        # The request layer is still well-formed — the application
        # service persists it with status=failed and completed_at.
        self.assertEqual(request.provider_key, "fixture_dev")
        self.assertEqual(request.request_key, f"instruments-{as_of.isoformat()}")

    def test_simulate_failure_method_toggles_flag(self) -> None:
        provider = FixtureDevInstrumentProvider()
        self.assertFalse(provider.is_simulating_failure)
        provider.simulate_failure()
        self.assertTrue(provider.is_simulating_failure)
        _, attempt, _ = provider.fetch_instruments(date(2026, 7, 31))
        self.assertEqual(attempt.status, ProviderAttemptStatus.FAILED)
        # reset() restores the success path
        provider.reset()
        self.assertFalse(provider.is_simulating_failure)
        _, attempt, batch = provider.fetch_instruments(date(2026, 7, 31))
        self.assertEqual(attempt.status, ProviderAttemptStatus.SUCCEEDED)
        self.assertIsNotNone(batch)

    def test_deserialize_records_round_trip(self) -> None:
        """The records JSON sidecar must round-trip back to domain Instruments."""

        _, _, batch = self._provider.fetch_instruments(date(2026, 7, 31))
        assert batch is not None
        from invest_pipeline.adapters.fixture_dev.adapter import _serialize_records

        sidecar = _serialize_records(batch.records)
        round_tripped = deserialize_records(sidecar)
        self.assertEqual(len(round_tripped), len(batch.records))
        for original, recovered in zip(batch.records, round_tripped, strict=True):
            self.assertEqual(original.symbol, recovered.symbol)
            self.assertEqual(original.exchange, recovered.exchange)
            self.assertEqual(original.name, recovered.name)
            self.assertEqual(original.instrument_type, recovered.instrument_type)
            self.assertEqual(original.list_date, recovered.list_date)
            self.assertEqual(original.status, recovered.status)
            self.assertEqual(original.underlying_index, recovered.underlying_index)
            self.assertEqual(original.category, recovered.category)

    def test_deserialize_records_rejects_unsupported_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            deserialize_records('{"schema_version": 999, "records": []}')

    def test_deserialize_records_rejects_non_list_records(self) -> None:
        with self.assertRaises(ValueError):
            deserialize_records('{"schema_version": 1, "records": "not-a-list"}')

    def test_deserialize_records_handles_none(self) -> None:
        self.assertEqual(deserialize_records(None), [])


if __name__ == "__main__":
    unittest.main()
