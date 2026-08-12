from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from invest_domain.market_data.models import (
    ProviderAttemptStatus,
    ProviderBatchStatus,
    ProviderFailureStage,
)
from invest_domain.market_data.price_limits import (
    KnownPriceLimit,
    UnlimitedPriceLimit,
)
from invest_pipeline.adapters.fixture_dev.price_limits import (
    FixtureDevStockPriceLimitsProvider,
    PriceLimitRecord,
)

TRADE_DATE = date(2026, 8, 11)


def _fetch(symbols: list[str]) -> tuple:
    """Helper that strips off the request from the returned triple."""

    request, attempt, batch = FixtureDevStockPriceLimitsProvider().fetch_price_limits(
        symbols, TRADE_DATE
    )
    return attempt, batch


def _record_for(symbol: str) -> PriceLimitRecord:
    _, batch = _fetch([symbol])
    assert batch is not None
    return batch.records[0]


class SuccessBundleTest(unittest.TestCase):
    """Deterministic success path covers every board and listing-status branch."""

    def test_success_bundle_contains_deterministic_price_limit_records(self) -> None:
        provider = FixtureDevStockPriceLimitsProvider()

        request, attempt, batch = provider.fetch_price_limits(
            ["600000", "600001", "688001"], TRADE_DATE
        )

        assert request.provider_key == "fixture_dev"
        assert request.dataset_key == "stock_price_limits"
        assert request.request_key == "price-limits-2026-08-11-600000-600001-688001"
        assert request.params == {
            "symbols": ["600000", "600001", "688001"],
            "trade_date": "2026-08-11",
        }
        assert attempt.status is ProviderAttemptStatus.SUCCEEDED
        assert batch is not None
        assert batch.status is ProviderBatchStatus.SUCCEEDED
        assert batch.warnings == ()

        normal, risk_warning, ipo = batch.records
        assert isinstance(normal.policy_result, KnownPriceLimit)
        assert normal.prev_close == Decimal("10.00")
        assert normal.limit_up_price == Decimal("11.00")
        assert normal.limit_down_price == Decimal("9.00")
        assert risk_warning.limit_up_price == Decimal("10.50")
        assert risk_warning.limit_down_price == Decimal("9.50")
        assert isinstance(ipo.policy_result, UnlimitedPriceLimit)
        assert ipo.policy_result.session_no == 5
        assert ipo.limit_up_price is None
        assert ipo.limit_down_price is None

    def test_same_fixture_request_has_same_payload_hash(self) -> None:
        provider = FixtureDevStockPriceLimitsProvider()

        first = provider.fetch_price_limits(["600000", "688001"], TRADE_DATE)[2]
        second = provider.fetch_price_limits(["600000", "688001"], TRADE_DATE)[2]

        assert first is not None and second is not None
        assert first.raw_payload_hash == second.raw_payload_hash
        assert first.records == second.records


class BoardCoverageTest(unittest.TestCase):
    """Task 1.2 acceptance: cover main / GEM / STAR / BSE / ST rules.

    Each board the :class:`PriceLimitPolicy` distinguishes has a
    deterministic rule in the on-disk fixture. The published facts
    must round-trip the policy's known / unlimited / unknown branches
    through the three-layer evidence bundle so a downstream task
    (Market Breadth v2 / Limit Sentiment) can rely on the regime-id
    binding.
    """

    def test_sse_main_normal_uses_ten_percent_rule(self) -> None:
        record = _record_for("600000")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("11.00")
        assert record.limit_down_price == Decimal("9.00")
        assert record.rule_version == "SSE_MAIN_2023_04_10"

    def test_sse_main_risk_warning_uses_five_percent_rule(self) -> None:
        record = _record_for("600001")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("10.50")
        assert record.limit_down_price == Decimal("9.50")
        assert record.rule_version == "SSE_MAIN_2023_04_10"

    def test_szse_main_normal_uses_ten_percent_rule(self) -> None:
        record = _record_for("000001")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("11.00")
        assert record.limit_down_price == Decimal("9.00")
        assert record.rule_version == "SZSE_MAIN_2023_04_10"

    def test_szse_gem_normal_uses_twenty_percent_rule(self) -> None:
        record = _record_for("300000")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("12.00")
        assert record.limit_down_price == Decimal("8.00")
        assert record.rule_version == "SZSE_GEM_2020_08_24"

    def test_szse_gem_risk_warning_uses_twenty_percent_rule(self) -> None:
        record = _record_for("300001")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("12.00")
        assert record.limit_down_price == Decimal("8.00")
        assert record.rule_version == "SZSE_GEM_2020_08_24"

    def test_sse_star_listed_session_above_ipo_window_uses_twenty_percent_rule(
        self,
    ) -> None:
        record = _record_for("688002")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("12.00")
        assert record.limit_down_price == Decimal("8.00")
        assert record.rule_version == "SSE_STAR_2019_07_22"

    def test_bse_normal_uses_thirty_percent_rule(self) -> None:
        record = _record_for("830000")
        assert isinstance(record.policy_result, KnownPriceLimit)
        assert record.limit_up_price == Decimal("13.00")
        assert record.limit_down_price == Decimal("7.00")
        assert record.rule_version == "BSE_BSE_2021_11_15"

    def test_bse_ipo_unlimited_session_publishes_unlimited_result(self) -> None:
        record = _record_for("830002")
        assert isinstance(record.policy_result, UnlimitedPriceLimit)
        assert record.policy_result.session_no == 1
        assert record.rule_version == "BSE_BSE_2021_11_15"
        assert record.limit_up_price is None
        assert record.limit_down_price is None


class BseRiskWarningFailClosedTest(unittest.TestCase):
    """The BSE regime has no ``risk_warning_ratio``; ST must fail closed."""

    def test_bse_risk_warning_is_rejected_as_policy_unknown(self) -> None:
        attempt, batch = _fetch(["830001"])

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_stage is ProviderFailureStage.CONTRACT
        assert attempt.error_code == "policy_unknown"
        assert batch is None


class SourceRefsBindingTest(unittest.TestCase):
    """Each published record must carry the matched regime's source refs."""

    def test_known_result_source_refs_include_regime_source(self) -> None:
        record = _record_for("600000")
        refs = record.source_refs
        assert "fixture_dev:price-limit:600000" in refs
        assert "official-rule:SSE_MAIN_2023_04_10" in refs

    def test_unlimited_result_source_refs_include_regime_source(self) -> None:
        record = _record_for("688001")
        refs = record.source_refs
        assert "fixture_dev:price-limit:688001" in refs
        assert "official-rule:SSE_STAR_2019_07_22" in refs


class FailClosedContractTest(unittest.TestCase):
    """The provider must surface every documented failure mode as a failed attempt."""

    def test_unknown_symbol_is_a_failed_attempt_without_batch(self) -> None:
        request, attempt, batch = FixtureDevStockPriceLimitsProvider().fetch_price_limits(
            ["000000"], TRADE_DATE
        )

        assert request.dataset_key == "stock_price_limits"
        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_stage is ProviderFailureStage.CONTRACT
        assert attempt.error_code == "unknown_symbol"
        assert batch is None

    def test_duplicate_symbol_is_a_failed_attempt_without_batch(self) -> None:
        attempt, batch = _fetch(["600000", "600000"])

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_stage is ProviderFailureStage.CONTRACT
        assert attempt.error_code == "unknown_symbol"
        assert batch is None

    def test_blank_symbol_is_a_failed_attempt_without_batch(self) -> None:
        attempt, batch = _fetch(["600000", " "])

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_code == "unknown_symbol"
        assert batch is None

    def test_non_string_symbol_is_a_failed_attempt_without_batch(self) -> None:
        attempt, batch = _fetch(["600000", 123])  # type: ignore[list-item]

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_code == "unknown_symbol"
        assert batch is None

    def test_empty_symbol_tuple_is_a_failed_attempt_without_batch(self) -> None:
        attempt, batch = _fetch([])

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_code == "unknown_symbol"
        assert batch is None

    def test_unsupported_board_fixture_is_fail_closed(self) -> None:
        _, attempt, batch = FixtureDevStockPriceLimitsProvider().fetch_price_limits(
            ["999999"], TRADE_DATE
        )

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_code == "policy_unknown"
        assert batch is None

    def test_invalid_date_is_a_failed_attempt_without_batch(self) -> None:
        _, attempt, batch = FixtureDevStockPriceLimitsProvider().fetch_price_limits(
            ["600000"], date(2026, 8, 12)
        )

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_stage is ProviderFailureStage.CONTRACT
        assert attempt.error_code == "unsupported_trade_date"
        assert batch is None

    def test_non_date_argument_is_a_failed_attempt_without_batch(self) -> None:
        _, attempt, batch = FixtureDevStockPriceLimitsProvider().fetch_price_limits(
            ["600000"],
            "2026-08-11",  # type: ignore[arg-type]
        )

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_code == "unsupported_trade_date"
        assert batch is None

    def test_simulated_failure_is_a_failed_attempt_without_batch(self) -> None:
        provider = FixtureDevStockPriceLimitsProvider(simulate_failure=True)
        _, attempt, batch = provider.fetch_price_limits(["600000"], TRADE_DATE)

        assert attempt.status is ProviderAttemptStatus.FAILED
        assert attempt.error_stage is ProviderFailureStage.PROVIDER
        assert attempt.error_code == "simulated_failure"
        assert batch is None

    def test_simulate_failure_and_reset_round_trip(self) -> None:
        provider = FixtureDevStockPriceLimitsProvider()
        assert not provider.is_simulating_failure

        provider.simulate_failure()
        assert provider.is_simulating_failure
        _, attempt, batch = provider.fetch_price_limits(["600000"], TRADE_DATE)
        assert attempt.status is ProviderAttemptStatus.FAILED
        assert batch is None

        provider.reset()
        assert not provider.is_simulating_failure
        _, attempt, batch = provider.fetch_price_limits(["600000"], TRADE_DATE)
        assert attempt.status is ProviderAttemptStatus.SUCCEEDED
        assert batch is not None


class ProviderKeyTest(unittest.TestCase):
    """The provider must identify itself with the public ``fixture_dev`` key."""

    def test_provider_key_is_fixture_dev(self) -> None:
        assert FixtureDevStockPriceLimitsProvider().provider_key == "fixture_dev"


class FixtureDevProviderIsNotRoutedTest(unittest.TestCase):
    """Intentional non-routing seam for Stage 4C Phase 0 Task 0.1.

    The provider is callable directly (and exercised by the rest of
    this module's tests), but the V2 catalog / routing layer must not
    treat it as a routable capability yet. Stage 4C Phase 0 Task 0.1
    freezes :attr:`ProviderCapability.STOCK_PRICE_LIMITS` and
    :attr:`Dataset.STOCK_PRICE_LIMITS` without registering any
    provider — the production path belongs to a later Stage 4C
    phase. This test pins the seam so a future regression that
    silently advertises ``STOCK_PRICE_LIMITS`` on ``fixture_dev``
    (or adds a pre-emptive declaration) surfaces here rather than
    enabling an unimplemented provider in the routing layer.
    """

    def test_select_providers_for_stock_price_limits_raises_no_eligible_provider(
        self,
    ) -> None:
        from invest_pipeline.provider_catalog import (
            FIXTURE_DEV,
            ProviderCapability,
        )
        from invest_pipeline.provider_routing.datasets import Dataset
        from invest_pipeline.provider_routing.selection import (
            NoEligibleProviderError,
            select_providers,
        )

        # The provider is importable and instantiable — the seam is
        # at the routing layer, not at the implementation surface.
        assert FixtureDevStockPriceLimitsProvider is not None

        # The FIXTURE_DEV declaration must not advertise
        # ``STOCK_PRICE_LIMITS`` in this slice. Mirrors the
        # ``Stage4CCapabilityEnumTest`` /
        # ``Stage4CDatasetRegistryTest`` guardrails.
        assert ProviderCapability.STOCK_PRICE_LIMITS not in FIXTURE_DEV.capabilities

        # And :func:`select_providers` for the dataset must raise the
        # documented :class:`NoEligibleProviderError` carrying the
        # persisted dataset string as its first argument.
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers((FIXTURE_DEV,), Dataset.STOCK_PRICE_LIMITS, enabled_only=False)
        self.assertEqual(ctx.exception.args[0], "stock_price_limits")
        self.assertIs(ctx.exception.dataset, Dataset.STOCK_PRICE_LIMITS)


if __name__ == "__main__":
    unittest.main()
