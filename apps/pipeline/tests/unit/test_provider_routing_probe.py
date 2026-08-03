"""Unit tests for the coverage-probe input builder (PR-05 follow-up).

The :mod:`invest_pipeline.provider_routing.probe` module exposes a
pure builder that converts successful provider probe results into
the ``provider_key -> symbol -> Sequence[DateRangeSample]`` mapping
:func:`invest_pipeline.provider_routing.coverage.calculate_coverage`
expects. The builder never touches the network, the filesystem or
the database — the tests construct everything in-memory and assert
on the deterministic output.

Coverage focus:

- The input dataclasses (:class:`CoverageProbeSample` /
  :class:`CoverageProbeInput`) reject malformed entries at
  construction time so a bad probe surfaces immediately rather than
  silently truncating the report.
- :func:`build_coverage_samples` produces a mapping that is
  bit-for-bit identical across repeated calls with the same input.
- The builder is round-trip compatible with
  :func:`invest_pipeline.provider_routing.coverage.calculate_coverage`
  so a downstream coverage-report caller can drop the output in
  without re-formatting.
- The canonical field-set constants (``NAV_FIELDS`` /
  ``DAILY_BARS_FIELDS`` / ``INSTRUMENT_FIELDS`` / ``CALENDAR_FIELDS``)
  match the shape the AkShare NAV / daily-bars / master-data /
  calendar mappers actually emit so a probe runner does not have
  to re-declare the field vocabulary per call.
"""

from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.provider_routing.coverage import (
    CoverageReport,
    DateRangeSample,
    InvalidCoverageSampleError,
    calculate_coverage,
)
from invest_pipeline.provider_routing.probe import (
    CALENDAR_FIELDS,
    DAILY_BARS_FIELDS,
    INSTRUMENT_FIELDS,
    NAV_FIELDS,
    CoverageProbeInput,
    CoverageProbeSample,
    build_coverage_samples,
)


class CoverageProbeFieldSetTest(unittest.TestCase):
    """The pre-built field-set constants match the adapter surfaces."""

    def test_nav_fields_match_akshare_nav_record(self) -> None:
        self.assertEqual(
            NAV_FIELDS,
            frozenset({"unit_nav", "accumulated_nav", "daily_growth_rate"}),
        )

    def test_daily_bars_fields_match_daily_bar_ohlcv(self) -> None:
        self.assertEqual(
            DAILY_BARS_FIELDS,
            frozenset({"open", "high", "low", "close", "volume", "amount"}),
        )

    def test_instrument_fields_match_master_data_shape(self) -> None:
        self.assertEqual(
            INSTRUMENT_FIELDS,
            frozenset(
                {"symbol", "name", "exchange", "list_date", "delist_date", "status"}
            ),
        )

    def test_calendar_fields_is_trade_date_only(self) -> None:
        self.assertEqual(CALENDAR_FIELDS, frozenset({"trade_date"}))


class CoverageProbeSampleValidationTest(unittest.TestCase):
    """:class:`CoverageProbeSample` enforces the basic shape at construction time."""

    def test_blank_symbol_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            CoverageProbeSample(
                symbol="   ",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
                fields=NAV_FIELDS,
            )
        self.assertEqual(ctx.exception.symbol, "   ")

    def test_end_date_before_start_date_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            CoverageProbeSample(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 29),
                fields=NAV_FIELDS,
            )
        self.assertEqual(ctx.exception.symbol, "510300")
        self.assertIn("on or after", ctx.exception.reason)

    def test_empty_fields_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError):
            CoverageProbeSample(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
                fields=frozenset(),
            )

    def test_non_frozenset_fields_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError):
            CoverageProbeSample(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
                fields={"unit_nav"},  # type: ignore[arg-type]
            )

    def test_blank_field_name_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError):
            CoverageProbeSample(
                symbol="510300",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 30),
                fields=frozenset({"unit_nav", ""}),
            )

    def test_same_start_and_end_date_is_accepted(self) -> None:
        sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        self.assertEqual(sample.start_date, sample.end_date)


class CoverageProbeInputValidationTest(unittest.TestCase):
    """:class:`CoverageProbeInput` enforces the basic shape at construction time."""

    def test_blank_provider_key_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            CoverageProbeInput(
                provider_key="",
                samples=(
                    CoverageProbeSample(
                        symbol="510300",
                        start_date=date(2026, 7, 30),
                        end_date=date(2026, 7, 30),
                        fields=NAV_FIELDS,
                    ),
                ),
            )
        self.assertEqual(ctx.exception.provider_key, "")

    def test_non_tuple_samples_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError):
            CoverageProbeInput(
                provider_key="akshare",
                samples=[  # type: ignore[arg-type]
                    CoverageProbeSample(
                        symbol="510300",
                        start_date=date(2026, 7, 30),
                        end_date=date(2026, 7, 30),
                        fields=NAV_FIELDS,
                    )
                ],
            )

    def test_non_sample_entry_is_rejected(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError):
            CoverageProbeInput(
                provider_key="akshare",
                samples=("not_a_sample",),  # type: ignore[arg-type]
            )


class BuildCoverageSamplesTest(unittest.TestCase):
    """:func:`build_coverage_samples` produces a deterministic, layered mapping."""

    def test_empty_inputs_yields_empty_mapping(self) -> None:
        self.assertEqual(build_coverage_samples(()), {})

    def test_single_input_yields_single_provider_entry(self) -> None:
        sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        mapping = build_coverage_samples(
            (CoverageProbeInput(provider_key="akshare", samples=(sample,)),)
        )
        self.assertEqual(
            mapping,
            {
                "akshare": {
                    "510300": (
                        DateRangeSample(
                            start_date=date(2026, 7, 30),
                            end_date=date(2026, 7, 30),
                            fields=NAV_FIELDS,
                        ),
                    ),
                },
            },
        )

    def test_groups_multiple_providers(self) -> None:
        nav_sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        bars_sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
            fields=DAILY_BARS_FIELDS,
        )
        mapping = build_coverage_samples(
            (
                CoverageProbeInput(
                    provider_key="akshare",
                    samples=(nav_sample,),
                ),
                CoverageProbeInput(
                    provider_key="fixture_dev",
                    samples=(bars_sample,),
                ),
            )
        )
        self.assertEqual(set(mapping), {"akshare", "fixture_dev"})
        self.assertEqual(set(mapping["akshare"]), {"510300"})
        self.assertEqual(set(mapping["fixture_dev"]), {"510300"})

    def test_groups_multiple_symbols_under_same_provider(self) -> None:
        sample_a = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        sample_b = CoverageProbeSample(
            symbol="159919",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        mapping = build_coverage_samples(
            (
                CoverageProbeInput(
                    provider_key="akshare",
                    samples=(sample_a, sample_b),
                ),
            )
        )
        self.assertEqual(
            set(mapping["akshare"]),
            {"510300", "159919"},
        )

    def test_preserves_per_symbol_range_order(self) -> None:
        first = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 25),
            fields=NAV_FIELDS,
        )
        second = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 26),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        mapping = build_coverage_samples(
            (
                CoverageProbeInput(
                    provider_key="akshare",
                    samples=(first, second),
                ),
            )
        )
        self.assertEqual(
            mapping["akshare"]["510300"],
            (
                DateRangeSample(
                    start_date=date(2026, 7, 23),
                    end_date=date(2026, 7, 25),
                    fields=NAV_FIELDS,
                ),
                DateRangeSample(
                    start_date=date(2026, 7, 26),
                    end_date=date(2026, 7, 30),
                    fields=NAV_FIELDS,
                ),
            ),
        )

    def test_output_round_trips_through_calculate_coverage(self) -> None:
        # The builder's output is meant to feed straight into
        # :func:`calculate_coverage`; the round-trip must yield the
        # expected :class:`CoverageReport` shape so a downstream
        # consumer can drop the mapping in without re-formatting.
        nav_sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        bars_sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
            fields=DAILY_BARS_FIELDS,
        )
        mapping = build_coverage_samples(
            (
                CoverageProbeInput(
                    provider_key="akshare",
                    samples=(nav_sample,),
                ),
                CoverageProbeInput(
                    provider_key="fixture_dev",
                    samples=(bars_sample,),
                ),
            )
        )
        report = calculate_coverage(mapping)
        self.assertIsInstance(report, CoverageReport)
        self.assertEqual(
            tuple(provider.provider_key for provider in report.providers),
            ("akshare", "fixture_dev"),
        )
        akshare_entry = report.providers[0]
        self.assertEqual(
            tuple(symbol.symbol for symbol in akshare_entry.symbols),
            ("510300",),
        )

    def test_repeated_calls_with_same_input_return_equal_mapping(self) -> None:
        sample = CoverageProbeSample(
            symbol="510300",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=NAV_FIELDS,
        )
        inputs = (CoverageProbeInput(provider_key="akshare", samples=(sample,)),)
        self.assertEqual(
            build_coverage_samples(inputs),
            build_coverage_samples(inputs),
        )

    def test_calendar_dataset_key_only_has_trade_date(self) -> None:
        # The calendar probe records the single ``trade_date`` field
        # only; pin it so a future broadening surfaces here.
        sample = CoverageProbeSample(
            symbol="*",
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
            fields=CALENDAR_FIELDS,
        )
        mapping = build_coverage_samples(
            (
                CoverageProbeInput(
                    provider_key="akshare",
                    samples=(sample,),
                ),
            )
        )
        report = calculate_coverage(mapping)
        symbol_coverage = report.providers[0].symbols[0]
        self.assertEqual(symbol_coverage.ranges[0].fields, CALENDAR_FIELDS)

    def test_non_sequence_inputs_raises(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            build_coverage_samples({})  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.provider_key, "<unknown>")
        self.assertIn("Sequence", ctx.exception.reason)

    def test_non_coverage_probe_input_entry_raises(self) -> None:
        with self.assertRaises(InvalidCoverageSampleError) as ctx:
            build_coverage_samples(("not_an_input",))  # type: ignore[arg-type]
        self.assertIn("CoverageProbeInput", ctx.exception.reason)


if __name__ == "__main__":
    unittest.main()
