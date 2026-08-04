"""Read-only provider coverage report (PR-05 follow-up, ETF matrix).

The :mod:`invest_pipeline.provider_routing.coverage` module exposes the
deterministic ``source × symbol × date-range × field`` grid; the
:class:`CoverageReport` it returns is the canonical input to any
operator-facing tooling. This module extends that surface with the
single report document the coverage CLI (and any future Dagster asset)
can serialise and ship without ever touching the network, the database
or the filesystem.

The model is intentionally minimal and pure:

* :class:`CoverageReportModel` is the rich, JSON-ready envelope; every
  nested value is hashable and deterministically ordered so two calls
  with the same inputs produce structurally equal reports.
* :class:`ProviderCoverageRow` collects the per-provider facts the CLI
  prints (``provider_key``, sorted symbols, requested range, covered
  range, row count, field completeness and warnings / errors).
* :class:`SymbolCoverageRow` collects the per-symbol facts the CLI
  prints (the requested range, the covered range derived from the
  probe samples, the record count, the union of covered fields and
  any non-fatal warnings surfaced by the adapter).
* :func:`build_coverage_report_model` converts the existing
  :class:`invest_pipeline.provider_routing.coverage.CoverageReport`
  (plus the same probe batches that fed it) into the rich model.
* :func:`serialize_coverage_report` returns a deterministic JSON
  document with ``sort_keys=True`` so two calls with the same inputs
  produce identical bytes; the deterministic ``content_hash`` lives on
  the model itself so the CLI can quote a stable identifier without
  re-hashing on every call.

The module never imports :mod:`invest_pipeline.provider_factory` or any
network / database layer; the report is reproducible bit-for-bit from
its inputs, satisfying matrix §6 "all sources traceable", PR-05
"deterministic coverage" and the V2 plan §3 Task 5 "real-network
acceptance + per-source real coverage reports" follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from invest_domain.shared.canonical import canonical_sha256

from invest_pipeline.provider_routing.coverage import (
    CoverageReport,
    DateRangeSample,
    SymbolCoverage,
)
from invest_pipeline.provider_routing.probe import DAILY_BARS_FIELDS


class CoverageReportBuildError(ValueError):
    """Raised when :func:`build_coverage_report_model` receives bad input.

    The exception carries a tuple ``(provider_key, symbol, reason)``
    so the CLI / Dagster wrapper can locate the offending row without
    re-parsing the message string. The builder never partially
    normalises a probe batch: any malformed input raises before the
    report is published.
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
class CoverageWarning:
    """A single non-fatal warning captured from the probe step.

    The CLI keeps the message verbatim (provider-supplied warnings
    never carry secrets; the existing
    :class:`invest_pipeline.adapters.errors.ProviderError` scrubbers
    strip any API key before the message reaches this model) and
    preserves the source ``(provider_key, symbol)`` so operators can
    trace each warning back to the underlying adapter call.
    """

    provider_key: str
    symbol: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise CoverageReportBuildError(
                str(self.provider_key),
                "<unknown>",
                "warning.provider_key must be a non-empty string",
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise CoverageReportBuildError(
                self.provider_key,
                str(self.symbol),
                "warning.symbol must be a non-empty string",
            )
        if not isinstance(self.message, str):
            raise CoverageReportBuildError(
                self.provider_key,
                self.symbol,
                "warning.message must be a string",
            )


@dataclass(frozen=True, slots=True)
class CoverageError:
    """A single failed probe step captured by the CLI runner.

    The model intentionally keeps the error ``code`` / ``message``
    pair so the CLI can surface a stable, machine-readable reason
    (mirroring :class:`invest_pipeline.adapters.errors.ProviderError`
    categories) without re-parsing free text. ``message`` is whatever
    the adapter surface produced; the CLI scrubber is responsible for
    stripping secrets before the message is persisted into the report.
    """

    provider_key: str
    symbol: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise CoverageReportBuildError(
                str(self.provider_key),
                "<unknown>",
                "error.provider_key must be a non-empty string",
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise CoverageReportBuildError(
                self.provider_key,
                str(self.symbol),
                "error.symbol must be a non-empty string",
            )
        if not isinstance(self.code, str) or not self.code.strip():
            raise CoverageReportBuildError(
                self.provider_key,
                self.symbol,
                "error.code must be a non-empty string",
            )
        if not isinstance(self.message, str):
            raise CoverageReportBuildError(
                self.provider_key,
                self.symbol,
                "error.message must be a string",
            )


@dataclass(frozen=True, slots=True)
class SymbolCoverageRow:
    """The per-symbol coverage facts the report ships to operators.

    Attributes
    ----------
    symbol:
        Provider-native symbol (``"510300"``). Preserved verbatim —
        no case folding, no trimming — so the row joins back to the
        adapter's :class:`ProviderBatch` ``records``.
    requested_start / requested_end:
        The inclusive date range the operator asked the CLI to probe.
        Either field may be :data:`None` if the runner did not pass a
        range for the symbol (e.g. an instrument-master probe); the
        CLI sets both to :data:`None` when the symbol was not
        inspected.
    covered_start / covered_end:
        The inclusive date range the union of the underlying probe
        samples actually covers. ``None`` when no probe sample was
        captured for the symbol (e.g. the adapter failed before
        returning a :class:`ProviderBatch`).
    record_count:
        The number of records the probe sample carried for the symbol.
        ``0`` when no records were returned.
    fields:
        Sorted tuple of field names the probe sample recorded for the
        symbol. Empty when no records were returned.
    requested_fields:
        Sorted tuple of field names the operator asked the CLI to
        require (``None`` when the operator did not pin a field set).
    warnings:
        Tuple of :class:`CoverageWarning` entries captured for the
        symbol during the probe iteration. Sorted deterministically by
        ``(message, symbol, provider_key)`` so the report serialises
        bit-for-bit.
    errors:
        Tuple of :class:`CoverageError` entries captured for the
        symbol during the probe iteration. Sorted deterministically by
        ``(code, message, symbol, provider_key)`` so the report
        serialises bit-for-bit.
    """

    symbol: str
    requested_start: date | None
    requested_end: date | None
    covered_start: date | None
    covered_end: date | None
    record_count: int
    fields: tuple[str, ...]
    requested_fields: tuple[str, ...] | None
    warnings: tuple[CoverageWarning, ...]
    errors: tuple[CoverageError, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise CoverageReportBuildError(
                "<unknown>",
                str(self.symbol),
                "SymbolCoverageRow.symbol must be a non-empty string",
            )
        for field_name in ("requested_start", "requested_end", "covered_start", "covered_end"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, date):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    f"SymbolCoverageRow.{field_name} must be a date or None, "
                    f"got {type(value).__name__}",
                )
        if not isinstance(self.record_count, int) or self.record_count < 0:
            raise CoverageReportBuildError(
                "<unknown>",
                self.symbol,
                f"SymbolCoverageRow.record_count must be a non-negative int, "
                f"got {self.record_count!r}",
            )
        if not isinstance(self.fields, tuple):
            raise CoverageReportBuildError(
                "<unknown>",
                self.symbol,
                f"SymbolCoverageRow.fields must be a tuple[str, ...], "
                f"got {type(self.fields).__name__}",
            )
        for field_name in self.fields:
            if not isinstance(field_name, str) or not field_name.strip():
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    f"SymbolCoverageRow.fields must contain only non-empty strings, "
                    f"got {field_name!r}",
                )
        if self.requested_fields is not None:
            if not isinstance(self.requested_fields, tuple):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    "SymbolCoverageRow.requested_fields must be a tuple[str, ...] "
                    f"or None, got {type(self.requested_fields).__name__}",
                )
            for field_name in self.requested_fields:
                if not isinstance(field_name, str) or not field_name.strip():
                    raise CoverageReportBuildError(
                        "<unknown>",
                        self.symbol,
                        "SymbolCoverageRow.requested_fields must contain only "
                        f"non-empty strings, got {field_name!r}",
                    )
        if (
            self.requested_start is not None
            and self.requested_end is not None
            and self.requested_end < self.requested_start
        ):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    "SymbolCoverageRow.requested_end must be on or after "
                    "requested_start",
                )
        if (
            self.covered_start is not None
            and self.covered_end is not None
            and self.covered_end < self.covered_start
        ):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    "SymbolCoverageRow.covered_end must be on or after covered_start",
                )
        if not isinstance(self.warnings, tuple):
            raise CoverageReportBuildError(
                "<unknown>",
                self.symbol,
                f"SymbolCoverageRow.warnings must be a tuple[CoverageWarning, ...], "
                f"got {type(self.warnings).__name__}",
            )
        for entry in self.warnings:
            if not isinstance(entry, CoverageWarning):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    f"SymbolCoverageRow.warnings must contain only CoverageWarning "
                    f"instances, got {type(entry).__name__}",
                )
        if not isinstance(self.errors, tuple):
            raise CoverageReportBuildError(
                "<unknown>",
                self.symbol,
                f"SymbolCoverageRow.errors must be a tuple[CoverageError, ...], "
                f"got {type(self.errors).__name__}",
            )
        for entry in self.errors:
            if not isinstance(entry, CoverageError):
                raise CoverageReportBuildError(
                    "<unknown>",
                    self.symbol,
                    f"SymbolCoverageRow.errors must contain only CoverageError "
                    f"instances, got {type(entry).__name__}",
                )


@dataclass(frozen=True, slots=True)
class ProviderCoverageRow:
    """The per-provider facts the report ships to operators.

    Attributes
    ----------
    provider_key:
        Stable lower-snake-case provider identifier (matches the
        :class:`invest_pipeline.provider_catalog.ProviderDeclaration`
        ``provider_key``).
    symbols:
        Sorted tuple of :class:`SymbolCoverageRow` entries (sorted
        by ``symbol`` in ascending order) so two reports built from
        the same probes produce structurally equal output.
    requested_start / requested_end:
        The inclusive date range the operator asked the CLI to probe
        for this provider. ``None`` when the CLI did not pin a range
        (e.g. instrument-master probes).
    requested_fields:
        Sorted tuple of field names the operator asked the CLI to
        require. ``None`` when the operator did not pin a field set.
    raw_payload_hash:
        Provider-side content hash (the :class:`ProviderBatch`
        ``raw_payload_hash`` for the most recent successful attempt).
        ``None`` when the probe failed before producing a batch.
    """

    provider_key: str
    symbols: tuple[SymbolCoverageRow, ...]
    requested_start: date | None
    requested_end: date | None
    requested_fields: tuple[str, ...] | None
    raw_payload_hash: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise CoverageReportBuildError(
                str(self.provider_key),
                "<unknown>",
                "ProviderCoverageRow.provider_key must be a non-empty string",
            )
        if not isinstance(self.symbols, tuple):
            raise CoverageReportBuildError(
                self.provider_key,
                "<unknown>",
                f"ProviderCoverageRow.symbols must be a tuple[SymbolCoverageRow, ...], "
                f"got {type(self.symbols).__name__}",
            )
        symbol_names = [entry.symbol for entry in self.symbols]
        if symbol_names != sorted(symbol_names):
            raise CoverageReportBuildError(
                self.provider_key,
                "<unknown>",
                "ProviderCoverageRow.symbols must be sorted by symbol in "
                "ascending order; the builder guarantees this and the caller "
                "is expected to receive an already-sorted tuple",
            )
        if len(set(symbol_names)) != len(symbol_names):
            raise CoverageReportBuildError(
                self.provider_key,
                "<unknown>",
                "ProviderCoverageRow.symbols must not contain duplicate symbols",
            )
        for entry in self.symbols:
            if not isinstance(entry, SymbolCoverageRow):
                raise CoverageReportBuildError(
                    self.provider_key,
                    "<unknown>",
                    f"ProviderCoverageRow.symbols must contain only "
                    f"SymbolCoverageRow instances, got {type(entry).__name__}",
                )
        for field_name in ("requested_start", "requested_end"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, date):
                raise CoverageReportBuildError(
                    self.provider_key,
                    "<unknown>",
                    f"ProviderCoverageRow.{field_name} must be a date or None, "
                    f"got {type(value).__name__}",
                )
        if (
            self.requested_start is not None
            and self.requested_end is not None
            and self.requested_end < self.requested_start
        ):
            raise CoverageReportBuildError(
                self.provider_key,
                "<unknown>",
                "ProviderCoverageRow.requested_end must be on or after "
                "requested_start",
            )
        if self.requested_fields is not None:
            if not isinstance(self.requested_fields, tuple):
                raise CoverageReportBuildError(
                    self.provider_key,
                    "<unknown>",
                    "ProviderCoverageRow.requested_fields must be a tuple[str, ...] "
                    f"or None, got {type(self.requested_fields).__name__}",
                )
            for field_name in self.requested_fields:
                if not isinstance(field_name, str) or not field_name.strip():
                    raise CoverageReportBuildError(
                        self.provider_key,
                        "<unknown>",
                        "ProviderCoverageRow.requested_fields must contain only "
                        f"non-empty strings, got {field_name!r}",
                    )
        if self.raw_payload_hash is not None and (
            not isinstance(self.raw_payload_hash, str)
            or not self.raw_payload_hash.strip()
        ):
                raise CoverageReportBuildError(
                    self.provider_key,
                    "<unknown>",
                    "ProviderCoverageRow.raw_payload_hash must be a non-empty "
                    "string when provided",
                )


@dataclass(frozen=True, slots=True)
class CoverageReportModel:
    """The rich, JSON-ready coverage report.

    The dataclass wraps the deterministic coverage matrix and adds the
    operator-facing fields the CLI / Dagster wrapper prints:

    * ``schema_version`` — pinned at ``1``; bumped whenever the
      serialised shape changes in a backward-incompatible way.
    * ``generated_at`` — the UTC instant the CLI built the report;
      every two calls within the same process carry different stamps
      so a downstream operator can tell re-runs apart.
    * ``content_hash`` — the deterministic SHA-256 of the report's
      business content (providers, symbols, ranges, record counts,
      fields, warnings / errors). The hash deliberately excludes
      ``generated_at`` so two reports built from the same probes in
      the same process produce the same identifier.
    * ``providers`` — sorted tuple of :class:`ProviderCoverageRow`
      entries (sorted by ``provider_key``).
    """

    schema_version: int
    generated_at: str
    content_hash: str
    providers: tuple[ProviderCoverageRow, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or self.schema_version < 1:
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.schema_version must be a positive int",
            )
        if not isinstance(self.generated_at, str) or not self.generated_at.strip():
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.generated_at must be a non-empty string",
            )
        if not isinstance(self.content_hash, str) or not self.content_hash.strip():
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.content_hash must be a non-empty string",
            )
        if not isinstance(self.providers, tuple):
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.providers must be a tuple[ProviderCoverageRow, ...]",
            )
        keys = [entry.provider_key for entry in self.providers]
        if keys != sorted(keys):
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.providers must be sorted by provider_key",
            )
        if len(set(keys)) != len(keys):
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "CoverageReportModel.providers must not contain duplicate provider keys",
            )


_REPORT_SCHEMA_VERSION = 1
"""Pinned schema version for the serialised coverage report JSON document."""


def _require_str(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoverageReportBuildError(
            "<unknown>",
            "<unknown>",
            f"{path} must be a non-empty string, got {value!r}",
        )
    return value


def _normalise_symbol_warnings(
    *,
    provider_key: str,
    symbol: str,
    warnings: Iterable[Any],
) -> tuple[CoverageWarning, ...]:
    normalised: list[CoverageWarning] = []
    for entry in warnings:
        if isinstance(entry, CoverageWarning):
            normalised.append(entry)
            continue
        if isinstance(entry, tuple) and len(entry) == 3:
            normalised.append(
                CoverageWarning(
                    provider_key=_require_str(entry[0], path="warning.provider_key"),
                    symbol=_require_str(entry[1], path="warning.symbol"),
                    message=str(entry[2]),
                )
            )
            continue
        raise CoverageReportBuildError(
            provider_key,
            symbol,
            "warnings entries must be CoverageWarning or (provider_key, symbol, message) tuples",
        )
    normalised.sort(key=lambda entry: (entry.message, entry.symbol, entry.provider_key))
    return tuple(normalised)


def _normalise_symbol_errors(
    *,
    provider_key: str,
    symbol: str,
    errors: Iterable[Any],
) -> tuple[CoverageError, ...]:
    normalised: list[CoverageError] = []
    for entry in errors:
        if isinstance(entry, CoverageError):
            normalised.append(entry)
            continue
        if isinstance(entry, tuple) and len(entry) == 4:
            normalised.append(
                CoverageError(
                    provider_key=_require_str(entry[0], path="error.provider_key"),
                    symbol=_require_str(entry[1], path="error.symbol"),
                    code=_require_str(entry[2], path="error.code"),
                    message=str(entry[3]),
                )
            )
            continue
        raise CoverageReportBuildError(
            provider_key,
            symbol,
            "errors entries must be CoverageError or (provider_key, symbol, code, message) tuples",
        )
    normalised.sort(
        key=lambda entry: (entry.code, entry.message, entry.symbol, entry.provider_key)
    )
    return tuple(normalised)


def _fields_tuple(fields: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for field_name in fields:
        if not isinstance(field_name, str) or not field_name.strip():
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                f"fields entries must be non-empty strings, got {field_name!r}",
            )
        if field_name in seen:
            continue
        seen.add(field_name)
        out.append(field_name)
    out.sort()
    return tuple(out)


def _coerce_date(value: Any, *, path: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                f"{path} must be an ISO date string, got {value!r} ({exc})",
            ) from exc
    raise CoverageReportBuildError(
        "<unknown>",
        "<unknown>",
        f"{path} must be a date or ISO string, got {type(value).__name__}",
    )


def _covered_range(
    samples: Sequence[DateRangeSample],
) -> tuple[date | None, date | None]:
    if not samples:
        return None, None
    starts = [sample.start_date for sample in samples]
    ends = [sample.end_date for sample in samples]
    return min(starts), max(ends)


def _record_counts(
    *,
    provider_key: str,
    symbol: str,
    record_counts: Mapping[str, int] | None,
) -> int:
    if record_counts is None:
        return 0
    value = record_counts.get(symbol)
    if value is None:
        return 0
    if not isinstance(value, int) or value < 0:
        raise CoverageReportBuildError(
            provider_key,
            symbol,
            f"record_counts[{symbol!r}] must be a non-negative int, got {value!r}",
        )
    return value


def _raw_payload_hash(
    *,
    provider_key: str,
    raw_payload_hashes: Mapping[str, str | None] | None,
) -> str | None:
    if raw_payload_hashes is None:
        return None
    if provider_key not in raw_payload_hashes:
        return None
    value = raw_payload_hashes[provider_key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CoverageReportBuildError(
            provider_key,
            "<unknown>",
            "raw_payload_hashes entries must be non-empty strings when provided",
        )
    return value


def build_symbol_coverage_row(
    *,
    symbol_coverage: SymbolCoverage,
    record_count: int,
    requested_start: date | None,
    requested_end: date | None,
    requested_fields: tuple[str, ...] | None,
    warnings: Iterable[Any] = (),
    errors: Iterable[Any] = (),
) -> SymbolCoverageRow:
    """Build a single :class:`SymbolCoverageRow` from a routing row.

    Exposed for tests and any future Dagster asset that wants to
    build the rich model directly without going through
    :func:`build_coverage_report_model`.
    """

    covered_start, covered_end = _covered_range(symbol_coverage.ranges)
    if covered_start is None:
        fields: tuple[str, ...] = ()
    else:
        merged: set[str] = set()
        for sample in symbol_coverage.ranges:
            merged.update(sample.fields)
        fields = _fields_tuple(merged)
    return SymbolCoverageRow(
        symbol=symbol_coverage.symbol,
        requested_start=requested_start,
        requested_end=requested_end,
        covered_start=covered_start,
        covered_end=covered_end,
        record_count=record_count,
        fields=fields,
        requested_fields=(
            _fields_tuple(requested_fields) if requested_fields is not None else None
        ),
        warnings=_normalise_symbol_warnings(
            provider_key="<pending>",
            symbol=symbol_coverage.symbol,
            warnings=warnings,
        ),
        errors=_normalise_symbol_errors(
            provider_key="<pending>",
            symbol=symbol_coverage.symbol,
            errors=errors,
        ),
    )


def build_provider_coverage_row(
    *,
    provider_key: str,
    coverage: CoverageReport,
    requested_start: date | None,
    requested_end: date | None,
    requested_fields: tuple[str, ...] | None,
    record_counts: Mapping[str, int] | None = None,
    raw_payload_hashes: Mapping[str, str | None] | None = None,
    warnings: Mapping[str, Sequence[Any]] | None = None,
    errors: Mapping[str, Sequence[Any]] | None = None,
) -> ProviderCoverageRow | None:
    """Build a :class:`ProviderCoverageRow` for ``provider_key``.

    Returns ``None`` when ``provider_key`` is not present in
    ``coverage`` so a CLI can detect the "no probe sample" case
    without having to scan the report twice. The ``warnings`` and
    ``errors`` mappings are keyed by symbol; entries that are not
    :class:`CoverageWarning` / :class:`CoverageError` instances are
    coerced from three- or four-tuples respectively.
    """

    provider_coverage = None
    for entry in coverage.providers:
        if entry.provider_key == provider_key:
            provider_coverage = entry
            break
    if provider_coverage is None:
        return None

    rows: list[SymbolCoverageRow] = []
    for symbol_coverage in provider_coverage.symbols:
        symbol_warnings = list((warnings or {}).get(symbol_coverage.symbol, ()))
        symbol_errors = list((errors or {}).get(symbol_coverage.symbol, ()))
        row = build_symbol_coverage_row(
            symbol_coverage=symbol_coverage,
            record_count=_record_counts(
                provider_key=provider_key,
                symbol=symbol_coverage.symbol,
                record_counts=record_counts,
            ),
            requested_start=requested_start,
            requested_end=requested_end,
            requested_fields=requested_fields,
            warnings=(),
            errors=(),
        )
        row = SymbolCoverageRow(
            symbol=row.symbol,
            requested_start=row.requested_start,
            requested_end=row.requested_end,
            covered_start=row.covered_start,
            covered_end=row.covered_end,
            record_count=row.record_count,
            fields=row.fields,
            requested_fields=row.requested_fields,
            warnings=_normalise_symbol_warnings(
                provider_key=provider_key,
                symbol=row.symbol,
                warnings=symbol_warnings,
            ),
            errors=_normalise_symbol_errors(
                provider_key=provider_key,
                symbol=row.symbol,
                errors=symbol_errors,
            ),
        )
        rows.append(row)
    return ProviderCoverageRow(
        provider_key=provider_key,
        symbols=tuple(rows),
        requested_start=requested_start,
        requested_end=requested_end,
        requested_fields=(
            _fields_tuple(requested_fields) if requested_fields is not None else None
        ),
        raw_payload_hash=_raw_payload_hash(
            provider_key=provider_key,
            raw_payload_hashes=raw_payload_hashes,
        ),
    )


def build_coverage_report_model(
    *,
    coverage: CoverageReport,
    requested_start: date | None = None,
    requested_end: date | None = None,
    requested_fields: Sequence[str] | None = None,
    generated_at: str | None = None,
    record_counts: Mapping[str, Mapping[str, int]] | None = None,
    raw_payload_hashes: Mapping[str, str | None] | None = None,
    warnings: Mapping[str, Mapping[str, Sequence[Any]]] | None = None,
    errors: Mapping[str, Mapping[str, Sequence[Any]]] | None = None,
) -> CoverageReportModel:
    """Build a :class:`CoverageReportModel` from a routing :class:`CoverageReport`.

    Parameters
    ----------
    coverage:
        The deterministic coverage matrix produced by
        :func:`invest_pipeline.provider_routing.coverage.calculate_coverage`.
    requested_start / requested_end:
        Inclusive date range the operator asked the CLI to probe.
        Optional; ``None`` means "not pinned" (e.g. instrument-master
        probes). The values are propagated to every row.
    requested_fields:
        Sorted tuple of field names the operator asked the CLI to
        require. ``None`` means "not pinned". The model propagates
        the value to every row but does **not** enforce a check — the
        matrix is read-only metadata, the runner surfaces any
        shortfall via :attr:`SymbolCoverageRow.fields`.
    generated_at:
        UTC instant the CLI built the report. ``None`` falls back to
        the current UTC time (formatted as ISO-8601 with the
        ``+00:00`` offset). The value is **not** included in the
        deterministic ``content_hash`` so two reports built from the
        same probes carry the same identifier.
    record_counts:
        Optional ``provider_key -> symbol -> count`` mapping carrying
        the record count the underlying adapter batch observed per
        symbol. Missing entries default to ``0`` so the matrix stays
        a faithful read-only snapshot of the probe iteration.
    raw_payload_hashes:
        Optional ``provider_key -> hex SHA-256`` mapping carrying the
        :class:`ProviderBatch` ``raw_payload_hash`` for the most
        recent successful attempt. Missing entries default to
        ``None`` so a failed attempt shows up as "no payload".
    warnings / errors:
        Optional ``provider_key -> symbol -> Sequence[CoverageWarning |
        CoverageError | tuple]`` mappings carrying the non-fatal
        warnings and typed errors the runner captured for each
        (provider, symbol) pair. Missing entries default to empty
        tuples. The builder normalises every entry into the
        dataclass shape and sorts the resulting tuples so the report
        serialises bit-for-bit.

    Returns
    -------
    CoverageReportModel
        Rich, JSON-ready, deterministic-by-content coverage report.
        The model carries one :class:`ProviderCoverageRow` per
        provider key the underlying ``coverage`` recorded, sorted by
        ``provider_key``.

    Raises
    ------
    CoverageReportBuildError
        When any nested field fails validation. The builder does not
        partially normalise an invalid input — the entire report is
        rejected so the operator can fix the upstream probe rather
        than chase a silently-truncated report.
    """

    if not isinstance(coverage, CoverageReport):
        raise CoverageReportBuildError(
            "<unknown>",
            "<unknown>",
            "build_coverage_report_model requires a CoverageReport instance, "
            f"got {type(coverage).__name__}",
        )

    requested_start = _coerce_date(requested_start, path="requested_start")
    requested_end = _coerce_date(requested_end, path="requested_end")
    if (
        requested_start is not None
        and requested_end is not None
        and requested_end < requested_start
    ):
        raise CoverageReportBuildError(
            "<unknown>",
            "<unknown>",
            "requested_end must be on or after requested_start",
        )

    requested_fields_tuple = (
        None if requested_fields is None else _fields_tuple(requested_fields)
    )

    from datetime import UTC, datetime

    if generated_at is None:
        generated_at_value = datetime.now(UTC).isoformat()
    else:
        if not isinstance(generated_at, str) or not generated_at.strip():
            raise CoverageReportBuildError(
                "<unknown>",
                "<unknown>",
                "generated_at must be a non-empty ISO-8601 string when provided",
            )
        generated_at_value = generated_at

    provider_rows: list[ProviderCoverageRow] = []
    for provider_coverage in coverage.providers:
        provider_key = provider_coverage.provider_key
        provider_record_counts = (
            record_counts.get(provider_key, {}) if record_counts is not None else {}
        )
        provider_warnings = (
            warnings.get(provider_key, {}) if warnings is not None else {}
        )
        provider_errors = (
            errors.get(provider_key, {}) if errors is not None else {}
        )
        row = build_provider_coverage_row(
            provider_key=provider_key,
            coverage=coverage,
            requested_start=requested_start,
            requested_end=requested_end,
            requested_fields=requested_fields_tuple,
            record_counts=provider_record_counts,
            raw_payload_hashes=raw_payload_hashes,
            warnings=provider_warnings,
            errors=provider_errors,
        )
        if row is not None:
            provider_rows.append(row)

    provider_rows.sort(key=lambda entry: entry.provider_key)

    model_without_hash = CoverageReportModel(
        schema_version=_REPORT_SCHEMA_VERSION,
        generated_at=generated_at_value,
        content_hash="pending",
        providers=tuple(provider_rows),
    )
    content_hash = _compute_content_hash(model_without_hash)
    return CoverageReportModel(
        schema_version=model_without_hash.schema_version,
        generated_at=model_without_hash.generated_at,
        content_hash=content_hash,
        providers=model_without_hash.providers,
    )


def _symbol_row_payload(row: SymbolCoverageRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "requested_start": row.requested_start.isoformat()
        if row.requested_start is not None
        else None,
        "requested_end": row.requested_end.isoformat()
        if row.requested_end is not None
        else None,
        "covered_start": row.covered_start.isoformat()
        if row.covered_start is not None
        else None,
        "covered_end": row.covered_end.isoformat() if row.covered_end is not None else None,
        "record_count": row.record_count,
        "fields": list(row.fields),
        "requested_fields": list(row.requested_fields)
        if row.requested_fields is not None
        else None,
        "warnings": [
            {
                "provider_key": entry.provider_key,
                "symbol": entry.symbol,
                "message": entry.message,
            }
            for entry in row.warnings
        ],
        "errors": [
            {
                "provider_key": entry.provider_key,
                "symbol": entry.symbol,
                "code": entry.code,
                "message": entry.message,
            }
            for entry in row.errors
        ],
    }


def _provider_row_payload(row: ProviderCoverageRow) -> dict[str, Any]:
    return {
        "provider_key": row.provider_key,
        "requested_start": row.requested_start.isoformat()
        if row.requested_start is not None
        else None,
        "requested_end": row.requested_end.isoformat()
        if row.requested_end is not None
        else None,
        "requested_fields": list(row.requested_fields)
        if row.requested_fields is not None
        else None,
        "raw_payload_hash": row.raw_payload_hash,
        "symbols": [_symbol_row_payload(entry) for entry in row.symbols],
    }


def _compute_content_hash(model: CoverageReportModel) -> str:
    """Return the deterministic SHA-256 of the model's business content.

    Excludes :attr:`generated_at` so two reports built from the same
    probes carry the same identifier; the canonical encoder strips
    any non-JSON-safe values and sorts keys deterministically.
    """

    payload: dict[str, Any] = {
        "schema_version": model.schema_version,
        "providers": [_provider_row_payload(entry) for entry in model.providers],
    }
    return canonical_sha256(payload)


def serialize_coverage_report(model: CoverageReportModel) -> str:
    """Return a deterministic JSON document for ``model``.

    The encoder uses ``sort_keys=True`` and the canonical sha256 hash
    so the same inputs always produce the same bytes; the resulting
    string is safe to ship on stdout and on disk for downstream
    parsers.
    """

    import json

    payload: dict[str, Any] = {
        "schema_version": model.schema_version,
        "generated_at": model.generated_at,
        "content_hash": model.content_hash,
        "providers": [_provider_row_payload(entry) for entry in model.providers],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def default_daily_bars_field_set() -> tuple[str, ...]:
    """Return the canonical ETF daily-bars field set the report references.

    Mirrors :data:`invest_pipeline.provider_routing.probe.DAILY_BARS_FIELDS`
    and exists so a CLI / Dagster asset does not have to import the
    probe module just to ask for the canonical field list.
    """

    return _fields_tuple(DAILY_BARS_FIELDS)


__all__ = [
    "CoverageError",
    "CoverageReportBuildError",
    "CoverageReportModel",
    "CoverageWarning",
    "ProviderCoverageRow",
    "SymbolCoverageRow",
    "build_coverage_report_model",
    "build_provider_coverage_row",
    "build_symbol_coverage_row",
    "default_daily_bars_field_set",
    "serialize_coverage_report",
]
