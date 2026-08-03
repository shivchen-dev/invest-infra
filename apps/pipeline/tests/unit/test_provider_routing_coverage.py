"""Unit tests for the read-only coverage matrix (PR-05).

The coverage matrix is a deterministic, in-memory model that records
the ``source × symbol × date-range × field`` grid an operator can use
to plan a historical backfill. The tests assert:

* :func:`calculate_coverage` normalises the input into a
  :class:`CoverageReport` whose outer entries are sorted by
  ``provider_key`` and whose inner entries are sorted by ``symbol``.
* A :class:`DateRangeSample` with ``end_date < start_date`` or with
  an empty field set is rejected at construction time; the calculator
  therefore never persists an invalid sample.
* An empty input mapping produces an empty report whose ``is_empty``
  flag is ``True``.
* A partial input (only some provider / symbol combinations) yields
  a partial report that preserves the caller-supplied per-symbol
  range order.
* Two calls with the same input produce structurally equal reports,
  pinning the "deterministic coverage" property the plan §3 Task 5
  acceptance calls out.
* The calculator never touches the network, the filesystem or the
  database — these tests construct everything in-memory and never
  import the runtime factory or any storage module.
"""

from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.provider_routing.coverage import (
    CoverageReport,
    DateRangeSample,
    InvalidCoverageSampleError,
    ProviderCoverage,
    SymbolCoverage,
    calculate_coverage,
)

_FULL_OHLCV_FIELDS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "amount"}
)


def _build_sample(
    *,
    start: str, end: str, fields: frozenset[str] | None = None
) -> DateRangeSample:
    """Build a :class:`DateRangeSample` for the tests.

    The helper accepts ISO date strings so the test bodies stay
    readable; the field set defaults to the canonical OHLCV set the
    rest of the pipeline uses.
    """

    return DateRangeSample(
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        fields=fields if fields is not None else _FULL_OHLCV_FIELDS,
    )


class DateRangeSampleValidationTest(unittest.TestCase):
    """:class:`DateRangeSample` enforces the basic shape at construction time."""

    def test_end_date_before_start_date_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DateRangeSample(
                start_date=date(2024, 5, 10),
                end_date=date(2024, 5, 9),
                fields=_FULL_OHLCV_FIELDS,
            )

    def test_empty_fields_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DateRangeSample(
                start_date=date(2024, 5, 10),
                end_date=date(2024, 5, 10),
                fields=frozenset(),
            )

    def test_non_frozenset_fields_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DateRangeSample(
                start_date=date(2024, 5, 10),
                end_date=date(2024, 5, 10),
                fields={"open", "close"},  # type: ignore[arg-type]
            )

    def test_non_date_arguments_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DateRangeSample(
                start_date="2024-05-10",  # type: ignore[arg-type]
                end_date=date(2024, 5, 10),
                fields=_FULL_OHLCV_FIELDS,
            )

    def test_blank_field_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DateRangeSample(
                start_date=date(2024, 5, 10),
                end_date=date(2024, 5, 10),
                fields=frozenset({"open", ""}),
            )

    def test_same_start_and_end_date_is_accepted(self) -> None:
        # A single-day range is a valid sample; the calculator must
        # not collapse it. The dataclass accepts ``start == end``
        # because a one-day probe is a legitimate coverage record.
        sample = DateRangeSample(
            start_date=date(2024, 5, 10),
            end_date=date(2024, 5, 10),
            fields=frozenset({"close"}),
        )
        self.assertEqual(sample.start_date, sample.end_date)


class CalculateCoverageEmptyTest(unittest.TestCase):
    """An empty input mapping produces an empty, deterministic report."""

    def test_empty_mapping_yields_empty_report(self) -> None:
        report = calculate_coverage({})
        self.assertIsInstance(report, CoverageReport)
        self.assertEqual(report.providers, ())
        self.assertTrue(report.is_empty)

    def test_empty_provider_mapping_yields_empty_provider_entry(self) -> None:
        report = calculate_coverage({"akshare": {}})
        self.assertEqual(
            report,
            CoverageReport(
                providers=(
                    ProviderCoverage(provider_key="akshare", symbols=()),
                )
            ),
        )
        self.assertFalse(report.is_empty)

    def test_non_mapping_input_raises(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            calculate_coverage([])  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.args[0], "<unknown>")
        self.assertIn("Mapping", ctx.exception.reason)


class CalculateCoverageOrderingTest(unittest.TestCase):
    """The output is sorted by ``provider_key`` and ``symbol``."""

    def test_providers_are_sorted_by_provider_key(self) -> None:
        samples = {
            "rsscast": {"510300": [_build_sample(start="2024-05-01", end="2024-05-09")]},
            "akshare": {"510300": [_build_sample(start="2024-05-01", end="2024-05-09")]},
            "fixture_dev": {
                "510300": [_build_sample(start="2024-05-01", end="2024-05-09")]
            },
        }
        report = calculate_coverage(samples)
        self.assertEqual(
            tuple(provider.provider_key for provider in report.providers),
            ("akshare", "fixture_dev", "rsscast"),
        )

    def test_symbols_are_sorted_within_each_provider(self) -> None:
        samples = {
            "akshare": {
                "600000": [_build_sample(start="2024-05-01", end="2024-05-09")],
                "159915": [_build_sample(start="2024-05-01", end="2024-05-09")],
                "510300": [_build_sample(start="2024-05-01", end="2024-05-09")],
            },
        }
        report = calculate_coverage(samples)
        self.assertEqual(len(report.providers), 1)
        provider = report.providers[0]
        self.assertEqual(
            tuple(symbol.symbol for symbol in provider.symbols),
            ("159915", "510300", "600000"),
        )

    def test_range_order_is_preserved_per_symbol(self) -> None:
        # The matrix is read-only metadata; the calculator must
        # preserve the caller-supplied order so an operator can
        # tell at a glance which probe ran first.
        first = _build_sample(start="2024-05-01", end="2024-05-05")
        second = _build_sample(start="2024-05-06", end="2024-05-09")
        third = _build_sample(
            start="2024-05-10",
            end="2024-05-12",
            fields=frozenset({"close"}),
        )
        report = calculate_coverage(
            {"akshare": {"510300": [first, second, third]}}
        )
        symbol_coverage = report.providers[0].symbols[0]
        self.assertEqual(symbol_coverage.ranges, (first, second, third))


class CalculateCoveragePartialTest(unittest.TestCase):
    """A partial input mapping produces a partial report."""

    def test_partial_input_yields_partial_report(self) -> None:
        # Only one of the two providers has coverage for
        # ``510300``. The report must include only the providers
        # the caller supplied — a missing provider is not
        # synthesised, the report is purely a read-only record.
        fixture_sample = _build_sample(
            start="2024-05-01", end="2024-05-09"
        )
        akshare_sample = _build_sample(
            start="2016-01-04", end="2016-01-08"
        )
        report = calculate_coverage(
            {
                "fixture_dev": {"510300": [fixture_sample]},
                "akshare": {"510300": [akshare_sample]},
            }
        )
        self.assertEqual(len(report.providers), 2)
        keys = {provider.provider_key for provider in report.providers}
        self.assertEqual(keys, {"fixture_dev", "akshare"})

    def test_partial_provider_coverage_drops_unsampled_symbols(self) -> None:
        # A provider with coverage for ``159915`` only must NOT
        # carry a phantom ``510300`` entry; the report mirrors
        # the input exactly.
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        report = calculate_coverage(
            {
                "akshare": {"159915": [sample]},
            }
        )
        provider = report.providers[0]
        self.assertEqual(provider.provider_key, "akshare")
        self.assertEqual(tuple(s.symbol for s in provider.symbols), ("159915",))


class CalculateCoverageDeterministicTest(unittest.TestCase):
    """Two calls with the same input return structurally equal reports."""

    def test_repeated_calls_with_same_input_return_equal_reports(self) -> None:
        sample_a = _build_sample(start="2024-05-01", end="2024-05-09")
        sample_b = _build_sample(
            start="2024-05-10", end="2024-05-19", fields=frozenset({"close"})
        )
        input_mapping = {
            "rsscast": {"510300": [sample_a, sample_b]},
            "akshare": {"510300": [sample_a]},
        }
        first = calculate_coverage(input_mapping)
        second = calculate_coverage(input_mapping)
        self.assertEqual(first, second)
        # Re-iterate determinism: the order of providers / symbols
        # / ranges must be identical across calls.
        self.assertEqual(
            [p.provider_key for p in first.providers],
            [p.provider_key for p in second.providers],
        )

    def test_input_ordering_does_not_affect_output_order(self) -> None:
        # The output is sorted regardless of input ``dict`` order;
        # this is the property that lets the coverage matrix be
        # used as a stable hash key for downstream comparisons.
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        first = calculate_coverage(
            {
                "rsscast": {"510300": [sample]},
                "akshare": {"510300": [sample]},
            }
        )
        second = calculate_coverage(
            {
                "akshare": {"510300": [sample]},
                "rsscast": {"510300": [sample]},
            }
        )
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(p.provider_key for p in first.providers),
            ("akshare", "rsscast"),
        )


class CalculateCoverageValidationTest(unittest.TestCase):
    """Invalid samples raise :class:`InvalidCoverageSampleError` with row context."""

    def test_non_string_provider_key_raises(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            calculate_coverage({123: {"510300": []}})  # type: ignore[dict-item]
        self.assertEqual(ctx.exception.provider_key, "123")
        self.assertEqual(ctx.exception.symbol, "<unknown>")

    def test_non_string_symbol_raises(self) -> None:
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            calculate_coverage(
                {"akshare": {123: [sample]}}  # type: ignore[dict-item]
            )
        self.assertEqual(ctx.exception.provider_key, "akshare")
        self.assertEqual(ctx.exception.symbol, "123")
        self.assertIn("non-empty string", ctx.exception.reason)

    def test_non_sample_entry_raises(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            calculate_coverage(
                {"akshare": {"510300": ["not_a_sample"]}}  # type: ignore[list-item]
            )
        self.assertEqual(ctx.exception.provider_key, "akshare")
        self.assertEqual(ctx.exception.symbol, "510300")
        self.assertIn("DateRangeSample", ctx.exception.reason)

    def test_invalid_date_range_in_sample_raises(self) -> None:
        # The dataclass validation fires first; the calculator
        # therefore propagates the ``ValueError`` from
        # :class:`DateRangeSample` rather than swallowing it.
        with self.assertRaises(ValueError):
            DateRangeSample(
                start_date=date(2024, 5, 10),
                end_date=date(2024, 5, 9),
                fields=_FULL_OHLCV_FIELDS,
            )


class CoverageReportModelTest(unittest.TestCase):
    """The :class:`CoverageReport` rejects unsorted / duplicate input."""

    def test_providers_must_be_sorted(self) -> None:
        provider_a = ProviderCoverage(provider_key="akshare", symbols=())
        provider_z = ProviderCoverage(provider_key="rsscast", symbols=())
        with self.assertRaises(ValueError):
            CoverageReport(providers=(provider_z, provider_a))

    def test_providers_must_not_duplicate(self) -> None:
        provider = ProviderCoverage(provider_key="akshare", symbols=())
        with self.assertRaises(ValueError):
            CoverageReport(providers=(provider, provider))

    def test_providers_must_be_a_tuple(self) -> None:
        provider = ProviderCoverage(provider_key="akshare", symbols=())
        with self.assertRaises(TypeError):
            CoverageReport(providers=[provider])  # type: ignore[arg-type]

    def test_provider_symbols_must_be_sorted(self) -> None:
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        symbols = (
            SymbolCoverage(symbol="510300", ranges=(sample,)),
            SymbolCoverage(symbol="159915", ranges=(sample,)),
        )
        with self.assertRaises(ValueError):
            ProviderCoverage(provider_key="akshare", symbols=symbols)

    def test_provider_symbols_must_not_duplicate(self) -> None:
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        symbols = (
            SymbolCoverage(symbol="510300", ranges=(sample,)),
            SymbolCoverage(symbol="510300", ranges=(sample,)),
        )
        with self.assertRaises(ValueError):
            ProviderCoverage(provider_key="akshare", symbols=symbols)

    def test_symbol_range_must_be_a_tuple(self) -> None:
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        with self.assertRaises(TypeError):
            SymbolCoverage(symbol="510300", ranges=[sample])  # type: ignore[arg-type]

    def test_symbol_rejects_blank_name(self) -> None:
        sample = _build_sample(start="2024-05-01", end="2024-05-09")
        with self.assertRaises(ValueError):
            SymbolCoverage(symbol="   ", ranges=(sample,))

    def test_provider_rejects_blank_key(self) -> None:
        with self.assertRaises(ValueError):
            ProviderCoverage(provider_key="", symbols=())


if __name__ == "__main__":
    unittest.main()
