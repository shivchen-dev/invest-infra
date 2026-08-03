"""Coverage-probe input builder (PR-05 follow-up, NAV / calendar).

This module extends :mod:`invest_pipeline.provider_routing.coverage`
with a pure input builder that converts a sequence of successful
provider probe results into the ``provider_key -> symbol ->
Sequence[DateRangeSample]`` mapping
:func:`invest_pipeline.provider_routing.coverage.calculate_coverage`
expects. The builder never touches the network, the filesystem or
the database; it is the typed seam an offline probe runner uses to
hand a successful provider fetch back to the read-only coverage
matrix.

The shape of the public API is intentionally small:

- :data:`NAV_FIELDS` / :data:`DAILY_BARS_FIELDS` /
  :data:`CALENDAR_FIELDS` — frozen sets of canonical field names a
  probe typically records per dataset. The constants exist so a probe
  runner does not have to re-declare the field vocabulary per call.
- :class:`CoverageProbeSample` — a single ``(symbol, start_date,
  end_date, fields)`` tuple the probe runner emits after a successful
  adapter call.
- :class:`CoverageProbeInput` — a bundle grouping
  ``provider_key`` + the per-symbol samples so the builder can be
  called once per probe iteration.
- :func:`build_coverage_samples` — the pure builder. The output is
  bit-for-bit deterministic and the builder raises
  :class:`invest_pipeline.provider_routing.coverage.InvalidCoverageSampleError`
  on a malformed input so a bad probe surfaces immediately rather
  than silently truncating the report.

The module is read-only and provider-agnostic. It accepts any
``provider_key`` string (the routing layer does not validate the
provider identity at this seam) so a probe runner can use the
builder for both AkShare NAV / calendar probes and any future source
that returns successful :class:`invest_domain.market_data.models.
ProviderBatch` rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from invest_pipeline.provider_routing.coverage import (
    DateRangeSample,
    InvalidCoverageSampleError,
)

NAV_FIELDS: frozenset[str] = frozenset(
    {"unit_nav", "accumulated_nav", "daily_growth_rate"}
)
"""Canonical field set for the AkShare NAV probe.

The constants mirror the field set the NAV mapper actually
populates on :class:`invest_pipeline.adapters.akshare.mapper.
AkshareNavRecord`; a probe that successfully surfaces those three
columns reports the full NAV surface so a downstream consumer can
plan a backfill against the documented ``etf_nav`` dataset key.
"""


DAILY_BARS_FIELDS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "amount"}
)
"""Canonical field set for the ETF daily-bars probe.

Mirrors the canonical OHLCV surface the daily-bars mapper stamps
on :class:`invest_domain.market_data.models.DailyBar`; the probe
records every column the rest of the pipeline expects.
"""


INSTRUMENT_FIELDS: frozenset[str] = frozenset(
    {"symbol", "name", "exchange", "list_date", "delist_date", "status"}
)
"""Canonical field set for the ETF master-data probe.

The constants mirror the field set the master-data mapper actually
populates on :class:`invest_domain.instruments.models.Instrument`;
probing every column keeps the coverage matrix faithful to the
documented ``etf_instruments`` dataset shape.
"""


CALENDAR_FIELDS: frozenset[str] = frozenset({"trade_date"})
"""Canonical field set for the trading-calendar probe.

The calendar is intentionally date-only; the probe records the
single ``trade_date`` field so a downstream consumer can plan a
backfill against the ``trading_calendar`` dataset key.
"""


@dataclass(frozen=True, slots=True)
class CoverageProbeSample:
    """A single ``(symbol, start_date, end_date, fields)`` probe sample.

    The dataclass is the typed seam between a successful adapter
    fetch and the read-only coverage calculator. ``fields`` is
    normalised to a :class:`frozenset` so the resulting
    :class:`DateRangeSample` stays hashable and the report is
    reproducible across Python sessions.

    Attributes
    ----------
    symbol:
        Provider-native symbol (for example ``"510300"``). The
        string is preserved verbatim — no trimming, no case folding.
    start_date:
        Inclusive start of the covered range. Must satisfy
        ``end_date >= start_date``; the builder surfaces a
        :class:`InvalidCoverageSampleError` for an inverted range.
    end_date:
        Inclusive end of the covered range.
    fields:
        Frozen set of field names the provider covered for the
        range. The builder rejects empty field sets so a probe that
        surfaces zero columns cannot silently inflate the coverage
        matrix.
    """

    symbol: str
    start_date: date
    end_date: date
    fields: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise InvalidCoverageSampleError(
                "<unknown>",
                str(self.symbol),
                "symbol must be a non-empty string",
            )
        if not isinstance(self.start_date, date) or not isinstance(
            self.end_date, date
        ):
            raise InvalidCoverageSampleError(
                "<unknown>",
                self.symbol,
                "start_date / end_date must be date instances",
            )
        if self.end_date < self.start_date:
            raise InvalidCoverageSampleError(
                "<unknown>",
                self.symbol,
                f"end_date {self.end_date.isoformat()} must be on or "
                f"after start_date {self.start_date.isoformat()}",
            )
        if not isinstance(self.fields, frozenset):
            raise InvalidCoverageSampleError(
                "<unknown>",
                self.symbol,
                f"fields must be a frozenset[str], "
                f"got {type(self.fields).__name__}",
            )
        if not self.fields:
            raise InvalidCoverageSampleError(
                "<unknown>",
                self.symbol,
                "fields must contain at least one field name",
            )
        for field_name in self.fields:
            if not isinstance(field_name, str) or not field_name.strip():
                raise InvalidCoverageSampleError(
                    "<unknown>",
                    self.symbol,
                    f"fields must contain only non-empty strings, "
                    f"got {field_name!r}",
                )


@dataclass(frozen=True, slots=True)
class CoverageProbeInput:
    """Bundle grouping ``provider_key`` + the per-symbol samples.

    A probe runner typically creates one
    :class:`CoverageProbeInput` per provider iteration; the
    builder consumes a sequence of inputs and produces a
    :func:`calculate_coverage`-compatible mapping. The dataclass
    keeps the per-provider :attr:`provider_key` immutable so two
    iterations can never accidentally mix sources in the same
    input.
    """

    provider_key: str
    samples: tuple[CoverageProbeSample, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_key, str)
            or not self.provider_key.strip()
        ):
            raise InvalidCoverageSampleError(
                str(self.provider_key),
                "<unknown>",
                "provider_key must be a non-empty string",
            )
        if not isinstance(self.samples, tuple):
            raise InvalidCoverageSampleError(
                self.provider_key,
                "<unknown>",
                f"samples must be a tuple[CoverageProbeSample, ...], "
                f"got {type(self.samples).__name__}",
            )
        for sample in self.samples:
            if not isinstance(sample, CoverageProbeSample):
                raise InvalidCoverageSampleError(
                    self.provider_key,
                    "<unknown>",
                    f"sample must be a CoverageProbeSample instance, "
                    f"got {type(sample).__name__}",
                )


def _normalise_sample(
    provider_key: str, sample: CoverageProbeSample
) -> DateRangeSample:
    """Build a :class:`DateRangeSample` from a :class:`CoverageProbeSample`.

    The dataclass ``__post_init__`` already validated the shape so
    the builder can construct the report-side dataclass directly.
    The wrapper exists so a future cross-row validation rule (for
    example "two ranges under the same symbol must not overlap"
    from the coverage calculator's :func:`_normalise_sample`) can
    be applied in one place.
    """

    return DateRangeSample(
        start_date=sample.start_date,
        end_date=sample.end_date,
        fields=sample.fields,
    )


def build_coverage_samples(
    inputs: Sequence[CoverageProbeInput],
) -> Mapping[str, Mapping[str, Sequence[DateRangeSample]]]:
    """Build a :func:`calculate_coverage`-compatible input mapping.

    Parameters
    ----------
    inputs:
        Sequence of :class:`CoverageProbeInput` entries. The builder
        groups samples by ``provider_key`` (the outer key) and
        ``symbol`` (the inner key); the per-symbol tuple preserves
        the caller-supplied order so the report stays faithful to
        the probe iteration.

    Returns
    -------
    Mapping[str, Mapping[str, Sequence[DateRangeSample]]]
        Nested mapping shaped exactly like the input
        :func:`invest_pipeline.provider_routing.coverage.
        calculate_coverage` expects. The per-symbol sequence is a
        tuple so callers cannot accidentally mutate the report
        after the builder hands it back; the result is in-memory
        only and bit-for-bit reproducible across Python sessions.

    Raises
    ------
    InvalidCoverageSampleError
        When an input fails dataclass validation. The builder does
        **not** partially normalise a malformed input — the entire
        mapping is rejected so the probe runner can fix the
        upstream failure rather than chase a silently-truncated
        report.
    """

    if not isinstance(inputs, Sequence):
        raise InvalidCoverageSampleError(
            "<unknown>",
            "<unknown>",
            f"inputs must be a Sequence, got {type(inputs).__name__}",
        )

    grouped: dict[str, dict[str, tuple[DateRangeSample, ...]]] = {}
    for entry in inputs:
        if not isinstance(entry, CoverageProbeInput):
            raise InvalidCoverageSampleError(
                "<unknown>",
                "<unknown>",
                f"input must be a CoverageProbeInput instance, "
                f"got {type(entry).__name__}",
            )
        provider_bucket = grouped.setdefault(entry.provider_key, {})
        for sample in entry.samples:
            symbol_bucket_dict = provider_bucket
            existing = symbol_bucket_dict.get(sample.symbol, ())
            symbol_bucket_dict[sample.symbol] = existing + (
                _normalise_sample(entry.provider_key, sample),
            )

    return grouped


__all__ = [
    "CALENDAR_FIELDS",
    "CoverageProbeInput",
    "CoverageProbeSample",
    "DAILY_BARS_FIELDS",
    "INSTRUMENT_FIELDS",
    "NAV_FIELDS",
    "build_coverage_samples",
]
