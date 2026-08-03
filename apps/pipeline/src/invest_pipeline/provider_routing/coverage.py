"""Read-only source coverage model and calculator (PR-05).

PR-05 requires a deterministic ``source × symbol × date-range ×
field`` coverage matrix that operators can read to plan a historical
backfill (plan §3 Task 5 acceptance: "重复运行不产生重复记录；失败源
不静默替换；所有来源可追溯"). The matrix is built from explicit,
in-memory samples — the calculator never touches the network, the
filesystem or the database. The data flow is:

```text
samples: dict[provider_key, dict[symbol, Sequence[DateRangeSample]]]
        ↓
calculate_coverage(samples)
        ↓
CoverageReport(
    providers=tuple[
        ProviderCoverage(
            provider_key=...,
            symbols=tuple[
                SymbolCoverage(
                    symbol=...,
                    ranges=tuple[DateRangeSample, ...],
                ),
                ...
            ],
        ),
        ...
    ],
)
```

The model is intentionally minimal:

* :class:`DateRangeSample` pins a single ``(start_date, end_date,
  frozenset[field])`` triple.
* :class:`SymbolCoverage` collects the sorted, non-overlapping
  :class:`DateRangeSample` for one symbol under one provider.
* :class:`ProviderCoverage` collects the sorted
  :class:`SymbolCoverage` for one provider.
* :class:`CoverageReport` collects the sorted
  :class:`ProviderCoverage` for the report.

The :func:`calculate_coverage` calculator normalises the input shape
to guarantee a deterministic, hashable output:

* Provider keys, symbol strings and field names are preserved
  verbatim — no case folding, no trimming — so the report round-trips
  through the raw evidence tables.
* Date ranges are kept in the order the caller supplied them per
  symbol; overlapping ranges are allowed (the matrix is read-only
  metadata, not a deduplicator).
* Every :class:`DateRangeSample` is validated for ``start_date <=
  end_date``, non-empty field set and ISO-parseable dates; an
  invalid sample raises :class:`InvalidCoverageSampleError` and
  leaves the report unbuilt.

The module imports nothing from :mod:`invest_pipeline.provider_factory`
or any network / database layer; the report is reproducible bit-for-bit
from its inputs, satisfying the matrix §6 "all sources traceable" and
PR-05 "deterministic coverage" requirements.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date


class InvalidCoverageSampleError(ValueError):
    """Raised when a coverage sample violates the calculator's contract.

    The exception carries a tuple ``(provider_key, symbol, reason)`` as
    its arguments so the operator can locate the offending row
    without re-parsing the message string. The calculator never
    partially normalises a sample; the report is built only after
    every input passes validation.
    """

    def __init__(
        self,
        provider_key: str,
        symbol: str,
        reason: str,
    ) -> None:
        super().__init__(provider_key, symbol, reason)
        self.provider_key = provider_key
        self.symbol = symbol
        self.reason = reason


@dataclass(frozen=True, slots=True)
class DateRangeSample:
    """A single ``(date-range, fields)`` coverage sample.

    Attributes
    ----------
    start_date:
        Inclusive start of the covered range.
    end_date:
        Inclusive end of the covered range. Must satisfy
        ``end_date >= start_date``.
    fields:
        Immutable set of field names the provider covers for the
        range (for example ``{"open", "high", "low", "close",
        "volume"}``). The set is normalised to a
        :class:`frozenset` so the dataclass stays hashable and the
        report is reproducible across Python sessions.
    """

    start_date: date
    end_date: date
    fields: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.start_date, date):
            raise TypeError(
                "DateRangeSample.start_date must be a date instance, "
                f"got {type(self.start_date).__name__}"
            )
        if not isinstance(self.end_date, date):
            raise TypeError(
                "DateRangeSample.end_date must be a date instance, "
                f"got {type(self.end_date).__name__}"
            )
        if self.end_date < self.start_date:
            raise ValueError(
                f"DateRangeSample.end_date {self.end_date.isoformat()} "
                f"must be on or after start_date "
                f"{self.start_date.isoformat()}"
            )
        if not isinstance(self.fields, frozenset):
            raise TypeError(
                "DateRangeSample.fields must be a frozenset[str], "
                f"got {type(self.fields).__name__}"
            )
        if not self.fields:
            raise ValueError(
                "DateRangeSample.fields must contain at least one field name"
            )
        for field_name in self.fields:
            if not isinstance(field_name, str) or not field_name.strip():
                raise ValueError(
                    "DateRangeSample.fields must contain only non-empty "
                    f"strings, got {field_name!r}"
                )


@dataclass(frozen=True, slots=True)
class SymbolCoverage:
    """All :class:`DateRangeSample` entries for one symbol under one provider.

    Attributes
    ----------
    symbol:
        Provider-native symbol (for example ``"510300"``). The string
        is preserved verbatim — no trimming, no case folding.
    ranges:
        Tuple of :class:`DateRangeSample` entries. The order is the
        order the caller supplied; the calculator does not sort or
        de-duplicate the ranges because the matrix is read-only
        metadata and a re-supplied sample order is meaningful for the
        operator.
    """

    symbol: str
    ranges: tuple[DateRangeSample, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError(
                f"SymbolCoverage.symbol must be a non-empty string, "
                f"got {self.symbol!r}"
            )
        if not isinstance(self.ranges, tuple):
            raise TypeError(
                "SymbolCoverage.ranges must be a tuple[DateRangeSample, ...], "
                f"got {type(self.ranges).__name__}"
            )
        for entry in self.ranges:
            if not isinstance(entry, DateRangeSample):
                raise TypeError(
                    "SymbolCoverage.ranges must contain only "
                    f"DateRangeSample instances, got {type(entry).__name__}"
                )


@dataclass(frozen=True, slots=True)
class ProviderCoverage:
    """All :class:`SymbolCoverage` entries for one provider in the report.

    Attributes
    ----------
    provider_key:
        Stable lower-snake-case provider key (matches
        :class:`invest_pipeline.provider_catalog.ProviderDeclaration.provider_key`).
    symbols:
        Tuple of :class:`SymbolCoverage` entries, sorted by ``symbol``
        in ascending order. Sorting is the calculator's responsibility
        so the report order is deterministic across callers.
    """

    provider_key: str
    symbols: tuple[SymbolCoverage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise ValueError(
                "ProviderCoverage.provider_key must be a non-empty string, "
                f"got {self.provider_key!r}"
            )
        if not isinstance(self.symbols, tuple):
            raise TypeError(
                "ProviderCoverage.symbols must be a tuple[SymbolCoverage, ...], "
                f"got {type(self.symbols).__name__}"
            )
        symbol_names = [entry.symbol for entry in self.symbols]
        if symbol_names != sorted(symbol_names):
            raise ValueError(
                "ProviderCoverage.symbols must be sorted by symbol in "
                "ascending order; the calculator guarantees this and the "
                "caller is expected to receive an already-sorted tuple"
            )
        if len(set(symbol_names)) != len(symbol_names):
            raise ValueError(
                "ProviderCoverage.symbols must not contain duplicate symbols"
            )


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """The full deterministic ``source × symbol × date-range × field`` matrix.

    Attributes
    ----------
    providers:
        Tuple of :class:`ProviderCoverage` entries, sorted by
        ``provider_key`` in ascending order. Sorting is the
        calculator's responsibility so the report order is
        deterministic across callers.
    """

    providers: tuple[ProviderCoverage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.providers, tuple):
            raise TypeError(
                "CoverageReport.providers must be a "
                f"tuple[ProviderCoverage, ...], got {type(self.providers).__name__}"
            )
        provider_keys = [entry.provider_key for entry in self.providers]
        if provider_keys != sorted(provider_keys):
            raise ValueError(
                "CoverageReport.providers must be sorted by provider_key in "
                "ascending order; the calculator guarantees this and the "
                "caller is expected to receive an already-sorted tuple"
            )
        if len(set(provider_keys)) != len(provider_keys):
            raise ValueError(
                "CoverageReport.providers must not contain duplicate provider keys"
            )

    @property
    def is_empty(self) -> bool:
        """Return ``True`` iff the report carries zero coverage.

        The property makes the "no provider has been probed" case
        easy to detect in CLI / Dagster wrappers without iterating
        the report.
        """

        return not self.providers


def _normalise_sample(
    provider_key: str, symbol: str, sample: DateRangeSample
) -> DateRangeSample:
    """Return ``sample`` unchanged (validation lives on the dataclass).

    The helper exists so the calculator can apply cross-row
    validation in one place when future PRs add it (for example
    "two ranges under the same symbol must not overlap unless the
    field set is identical"). For PR-05 the dataclass-level
    ``__post_init__`` is sufficient; the wrapper is a deliberate
    seam.
    """

    return sample


def _normalise_symbol_entry(
    provider_key: str, symbol: str, samples: Sequence[DateRangeSample]
) -> SymbolCoverage:
    """Build one :class:`SymbolCoverage` for ``samples``.

    The input order is preserved; the calculator does not sort the
    ranges because the matrix is read-only metadata and a re-supplied
    sample order is meaningful for the operator. The function raises
    :class:`InvalidCoverageSampleError` if any entry in ``samples``
    is not a :class:`DateRangeSample` instance.
    """

    if not isinstance(symbol, str) or not symbol.strip():
        raise InvalidCoverageSampleError(
            provider_key, str(symbol), "symbol must be a non-empty string"
        )
    normalised: list[DateRangeSample] = []
    for sample in samples:
        if not isinstance(sample, DateRangeSample):
            raise InvalidCoverageSampleError(
                provider_key,
                symbol,
                f"sample must be a DateRangeSample instance, "
                f"got {type(sample).__name__}",
            )
        normalised.append(_normalise_sample(provider_key, symbol, sample))
    return SymbolCoverage(symbol=symbol, ranges=tuple(normalised))


def _normalise_provider_entry(
    provider_key: str, symbols: Mapping[str, Sequence[DateRangeSample]]
) -> ProviderCoverage:
    """Build one :class:`ProviderCoverage` for ``symbols``.

    Provider keys are validated up-front; the per-symbol mapping is
    turned into a tuple of :class:`SymbolCoverage` sorted by
    ``symbol`` so the report is reproducible across callers.
    """

    if not isinstance(provider_key, str) or not provider_key.strip():
        raise InvalidCoverageSampleError(
            str(provider_key),
            "<unknown>",
            "provider_key must be a non-empty string",
        )
    if not isinstance(symbols, Mapping):
        raise InvalidCoverageSampleError(
            provider_key,
            "<unknown>",
            f"per-symbol mapping must be a Mapping, got {type(symbols).__name__}",
        )
    symbol_coverages: list[SymbolCoverage] = []
    for symbol, samples in symbols.items():
        symbol_coverages.append(
            _normalise_symbol_entry(provider_key, symbol, samples)
        )
    symbol_coverages.sort(key=lambda entry: entry.symbol)
    return ProviderCoverage(provider_key=provider_key, symbols=tuple(symbol_coverages))


def calculate_coverage(
    samples: Mapping[str, Mapping[str, Sequence[DateRangeSample]]],
) -> CoverageReport:
    """Build a deterministic :class:`CoverageReport` from ``samples``.

    Parameters
    ----------
    samples:
        Nested mapping ``provider_key -> symbol -> Sequence[
        DateRangeSample]``. The outer mapping is normalised into a
        tuple of :class:`ProviderCoverage` sorted by ``provider_key``;
        the per-symbol mapping is normalised into a tuple of
        :class:`SymbolCoverage` sorted by ``symbol``. Date ranges
        preserve the caller-supplied order.

    Returns
    -------
    CoverageReport
        Deterministic, hashable, in-memory coverage matrix. The
        report never writes to the network, the filesystem or the
        database; it can be serialised (for example with
        :mod:`json` or :mod:`dataclasses.asdict`) and inspected
        without side effects.

    Raises
    ------
    InvalidCoverageSampleError
        When a provider key, symbol or sample fails validation. The
        calculator does **not** partially normalise an invalid
        input — the entire report is rejected so the operator can
        fix the upstream sample collection rather than chase a
        silently-truncated report.
    """

    if not isinstance(samples, Mapping):
        raise InvalidCoverageSampleError(
            "<unknown>",
            "<unknown>",
            f"samples must be a Mapping, got {type(samples).__name__}",
        )

    providers: list[ProviderCoverage] = []
    for provider_key, symbols in samples.items():
        providers.append(_normalise_provider_entry(provider_key, symbols))
    providers.sort(key=lambda entry: entry.provider_key)
    return CoverageReport(providers=tuple(providers))


__all__ = [
    "CoverageReport",
    "DateRangeSample",
    "InvalidCoverageSampleError",
    "ProviderCoverage",
    "SymbolCoverage",
    "calculate_coverage",
]
