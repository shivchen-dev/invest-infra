"""Read-only, opt-in provider coverage CLI (PR-05 follow-up).

Stage 1 PR-05 shipped the deterministic
``source × symbol × date-range × field`` coverage matrix the rest of
the pipeline can consume. This CLI adds the operator-facing surface
that runs the matrix against the V2 ETF Provider adapters in three
explicit modes:

* **Offline mode (default).** The CLI uses the in-repo
  :class:`invest_pipeline.adapters.fixture_dev.adapter.
  FixtureDevInstrumentProvider` and never reaches the network.
* **Real-network opt-in.** When ``--provider cifangquant`` is passed
  the CLI builds :class:`CifangQuantInstrumentProvider` through
  :func:`invest_pipeline.provider_factory.build_provider` and accepts
  the documented triple opt-in
  (``INVEST_PIPELINE_CIFANG_ENABLED=true``,
  ``INVEST_PIPELINE_CIFANG_API_KEY`` and ``--confirm-network``).
* **AkShare opt-in.** When ``--provider akshare`` is passed the CLI
  builds :class:`AkshareInstrumentProvider` through the same runtime
  factory and requires ``INVEST_PIPELINE_AKSHARE_ENABLED=true`` plus
  ``--confirm-network``.

When a real-provider opt-in is incomplete the CLI prints a single
concise ``refused:`` line on stderr and exits non-zero
*without ever opening a TCP connection*.

The CLI is intentionally minimal and intentionally safe-by-default:

* ``--symbols`` is required (1..20, no duplicates, no blank entries).
  ETF symbol list stays bounded because the underlying Cifang adapter
  enforces the documented 50-symbol chunking rule and the probe
  runner fans the input out one chunk at a time.
* ``--start-date`` / ``--end-date`` are optional; when both are passed
  they must parse as ``YYYY-MM-DD`` and ``start_date <= end_date``.
  When either is omitted the CLI defaults to the
  ``etf_daily_bars`` fixture's six-day window (2026-07-23 .. 2026-07-30)
  so a default ``make provider-coverage`` run produces a stable,
  inspectable report without any date arithmetic.
* ``--provider`` accepts the documented Provider keys
  (``fixture_dev``, ``cifangquant`` or ``akshare``). ``cifangquant`` and
  ``akshare`` require their explicit opt-in flags plus
  ``--confirm-network``; ``fixture_dev`` never needs that flag.
* ``--dataset`` is fixed at ``etf_daily_bars`` for the initial slice;
  the validator rejects every other value because the report's
  field-completeness contract is the OHLCV surface the daily-bars
  mappers stamp on :class:`invest_domain.market_data.models.DailyBar`.
* The CLI never prints the API key, raw payload, request headers,
  exception reprs (which may embed secrets) or absolute filesystem
  paths. Errors are surfaced as a single short stderr line plus a
  non-zero exit code; success emits one deterministic redacted JSON
  line on stdout.

The CLI does not write to PostgreSQL, does not invoke Dagster assets,
does not perform backfill, and does not enable QuickTiny / RssCast as
ETF daily providers. AkShare is available here only through its explicit
opt-in path; the catalog's other capability declarations remain unchanged.

This module never touches the network during construction or
validation; tests construct stub providers that return canned
evidence so the suite runs without ever importing the live
:mod:`httpx` / :class:`CifangClient` / :class:`AkshareClient` clients.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from invest_domain.instruments.models import Instrument
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)

from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    ProviderError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.provider_coverage_plan import select_active_etf_symbols
from invest_pipeline.provider_coverage_report import (
    CoverageError,
    CoverageReportBuildError,
    CoverageReportModel,
    CoverageWarning,
    build_coverage_report_model,
    default_daily_bars_field_set,
    serialize_coverage_report,
)
from invest_pipeline.provider_factory import (
    KNOWN_PROVIDER_KEYS,
    build_provider,
)
from invest_pipeline.provider_routing.coverage import (
    DateRangeSample,
    calculate_coverage,
)

__all__ = [
    "CoverageCLIConfigError",
    "ProviderCoverageRunner",
    "build_parser",
    "default_fixture_window",
    "main",
    "run_coverage",
]


_PROVIDER_KEY_ENV = "INVEST_PIPELINE_PROVIDER_KEY"
_CIFANG_ENABLED_ENV = "INVEST_PIPELINE_CIFANG_ENABLED"
_CIFANG_API_KEY_ENV = "INVEST_PIPELINE_CIFANG_API_KEY"
_AKSHARE_ENABLED_ENV = "INVEST_PIPELINE_AKSHARE_ENABLED"
_AKSHARE_TOKEN_ENV = "INVEST_PIPELINE_AKSHARE_TOKEN"

_FIXTURE_DEV_KEY = "fixture_dev"
_CIFANG_KEY = "cifangquant"
_AKSHARE_KEY = "akshare"
_DAILY_BARS_DATASET_KEY = "etf_daily_bars"

_REDACTED = "***"

_MIN_SYMBOLS = 1
_MAX_SYMBOLS = 20
_MAX_DATE_RANGE_CALENDAR_DAYS = 365

_FIXTURE_DEFAULT_START = date(2026, 7, 23)
_FIXTURE_DEFAULT_END = date(2026, 7, 30)

_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CoverageCLIConfigError(Exception):
    """Raised when the CLI inputs are incomplete or unsafe.

    The CLI translates this into an exit code of ``2`` and a single
    short line on stderr. It is **not** a provider-level error; the
    CLI refuses to construct the provider or open any database /
    network connection whenever this is raised.
    """


@dataclass(frozen=True, slots=True)
class _ProbeResult:
    """Bundle of evidence the probe runner returns per (provider, symbol).

    The runner treats the Provider as a black-box and lifts only the
    safe attributes (provider key, attempt status, batch status,
    record count, raw payload hash and warnings) into the report.
    The dataclass is intentionally narrow so tests can build canned
    results without invoking any real adapter call.
    """

    provider_key: str
    symbol: str
    start_date: date
    end_date: date
    attempt_status: ProviderAttemptStatus
    batch_status: ProviderBatchStatus | None
    record_count: int
    raw_payload_hash: str | None
    warnings: tuple[str, ...]
    error_code: str | None
    error_message: str | None
    error_stage: ProviderFailureStage | None


class _CoverageProviderPort(Protocol):
    """Minimal surface :func:`run_coverage` needs to drive one probe.

    Mirrors the existing :class:`EtfMarketDataProvider` port methods so
    a real adapter satisfies it via duck-typing; tests inject stubs
    that record calls and return canned evidence without ever
    opening a socket.
    """

    provider_key: str

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]: ...

    def close(self) -> None: ...


def _scrub(message: str, token: str) -> str:
    """Return ``message`` with every ``token`` occurrence replaced by ``***``.

    The helper is a no-op when ``token`` is empty so the test surface
    stays predictable. Every adapter already scrubs the API key out of
    error messages; this is belt-and-braces against a future
    regression.
    """

    if not token or not message:
        return message
    return message.replace(token, _REDACTED)


def default_fixture_window() -> tuple[date, date]:
    """Return the bounded default date window the CLI uses when the caller omits one.

    The window mirrors the ``fixture_dev`` ETF daily-bars fixture
    (2026-07-23..2026-07-30) so a default ``provider-coverage`` run
    always produces a stable, inspectable report without any date
    arithmetic on the operator side.
    """

    return _FIXTURE_DEFAULT_START, _FIXTURE_DEFAULT_END


def parse_symbols(raw: str) -> list[str]:
    """Parse ``--symbols`` into a deduplicated list of 1..20 entries.

    Whitespace around each entry is stripped; empty entries are
    rejected; duplicates are rejected with the offending value listed
    in the message. Pure so unit tests can drive it with arbitrary
    strings without touching the environment.
    """

    if not isinstance(raw, str):
        raise CoverageCLIConfigError("--symbols must be a string")
    parts = [segment.strip() for segment in raw.split(",")]
    if any(not segment for segment in parts):
        raise CoverageCLIConfigError("--symbols must not contain empty entries")
    if len(parts) < _MIN_SYMBOLS or len(parts) > _MAX_SYMBOLS:
        raise CoverageCLIConfigError(
            f"--symbols must contain between {_MIN_SYMBOLS} and {_MAX_SYMBOLS} "
            f"entries, got {len(parts)}"
        )
    if len(set(parts)) != len(parts):
        duplicates = sorted({symbol for symbol in parts if parts.count(symbol) > 1})
        raise CoverageCLIConfigError(
            f"--symbols must not contain duplicates: {','.join(duplicates)}"
        )
    return parts


def parse_iso_date(
    raw: str | None,
    *,
    field_name: str,
    fallback: date | None = None,
    today: date | None = None,
) -> date | None:
    """Parse a ``YYYY-MM-DD`` value into a :class:`date` and reject future dates.

    ``raw=None`` returns ``fallback`` so the CLI can default to the
    fixture window without branching at the call site. Future dates
    are rejected unless ``today`` is also ``None`` (the parser is
    then used in tests without a clock).
    """

    if raw is None:
        return fallback
    if not isinstance(raw, str) or not raw.strip():
        raise CoverageCLIConfigError(f"--{field_name} must be a non-empty string")
    if not _ISO_DATE_PATTERN.match(raw):
        raise CoverageCLIConfigError(
            f"--{field_name} must be YYYY-MM-DD, got {raw!r}"
        )
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise CoverageCLIConfigError(
            f"--{field_name} must be YYYY-MM-DD: {exc}"
        ) from exc
    if today is not None and parsed > today:
        raise CoverageCLIConfigError(
            f"--{field_name} must not be in the future "
            f"(got {parsed.isoformat()}, today is {today.isoformat()})"
        )
    return parsed


def validate_range(
    *,
    start_date: date | None,
    end_date: date | None,
    today: date | None,
) -> tuple[date, date]:
    """Resolve the (start, end) probe window and reject inverted / future ranges.

    When ``start_date`` or ``end_date`` is ``None`` the function falls
    back to the fixture window so the default CLI run produces a
    bounded, inspectable report.
    """

    if start_date is None and end_date is None:
        start_date, end_date = default_fixture_window()
    elif start_date is None:
        start_date = _FIXTURE_DEFAULT_START
    elif end_date is None:
        end_date = _FIXTURE_DEFAULT_END

    if start_date > end_date:
        raise CoverageCLIConfigError(
            f"--start-date ({start_date.isoformat()}) must not be after "
            f"--end-date ({end_date.isoformat()})"
        )
    span = (end_date - start_date).days + 1
    if span > _MAX_DATE_RANGE_CALENDAR_DAYS:
        raise CoverageCLIConfigError(
            f"date range spans {span} calendar days; the coverage CLI refuses "
            f"to probe more than {_MAX_DATE_RANGE_CALENDAR_DAYS} calendar days "
            "in a single run"
        )
    if today is not None and end_date > today:
        raise CoverageCLIConfigError(
            f"--end-date ({end_date.isoformat()}) must not be in the future "
            f"(today is {today.isoformat()})"
        )
    return start_date, end_date


def _resolve_provider_key(
    env: Mapping[str, str] | None,
    *,
    explicit: str | None,
) -> str:
    """Return the configured provider key, falling back to ``fixture_dev``.

    Reads the mapping directly so callers can drive the function in
    tests without touching :data:`os.environ`.
    """

    if explicit is not None:
        if explicit not in KNOWN_PROVIDER_KEYS:
            raise CoverageCLIConfigError(
                f"--provider {explicit!r} is not supported by the coverage CLI; "
                f"expected one of {sorted(KNOWN_PROVIDER_KEYS)}"
            )
        if explicit not in (_FIXTURE_DEV_KEY, _CIFANG_KEY, _AKSHARE_KEY):
            raise CoverageCLIConfigError(
                f"--provider {explicit!r} is not enabled as an ETF daily "
                f"provider in this slice; expected {_FIXTURE_DEV_KEY!r}, "
                f"{_CIFANG_KEY!r} or {_AKSHARE_KEY!r}"
            )
        return explicit
    if env is None:
        env = os.environ
    return str(env.get(_PROVIDER_KEY_ENV, _FIXTURE_DEV_KEY) or _FIXTURE_DEV_KEY)


def _cifang_enabled(env: Mapping[str, str] | None) -> bool:
    """Return whether the Cifang opt-in flag is set in ``env``."""

    if env is None:
        env = os.environ
    value = env.get(_CIFANG_ENABLED_ENV, "")
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _akshare_enabled(env: Mapping[str, str] | None) -> bool:
    """Return whether the AkShare opt-in flag is set in ``env``."""

    if env is None:
        env = os.environ
    value = env.get(_AKSHARE_ENABLED_ENV, "")
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _configured_cifang_token() -> str:
    """Return the configured Cifang API key, or an empty string on failure."""

    try:
        return CifangSettings().api_key.get_secret_value()
    except Exception:
        return ""


def _configured_akshare_token(settings: AkshareSettings | None = None) -> str:
    """Return the configured AkShare token without exposing it in output."""

    if settings is not None:
        try:
            return settings.token.get_secret_value()
        except Exception:
            return ""
    value = os.environ.get(_AKSHARE_TOKEN_ENV, "")
    return value if isinstance(value, str) else ""


def validate_provider_opt_in(
    *,
    provider_key: str,
    cifang_enabled: bool | None,
    confirm_network: bool,
    akshare_enabled: bool | None = None,
) -> None:
    """Reject the run unless the real-provider opt-in gates are aligned.

    ``fixture_dev`` never reaches the network; ``cifangquant`` requires
    ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and ``--confirm-network``;
    ``akshare`` requires ``INVEST_PIPELINE_AKSHARE_ENABLED=true`` and
    ``--confirm-network``.
    """

    if provider_key == _FIXTURE_DEV_KEY:
        return
    if provider_key == _CIFANG_KEY:
        if not cifang_enabled:
            raise CoverageCLIConfigError(
                f"{_CIFANG_ENABLED_ENV}=true is required to run the provider "
                "coverage CLI with --provider cifangquant (ADR-0011 §3); "
                "set it to acknowledge the real-API opt-in"
            )
        if not confirm_network:
            raise CoverageCLIConfigError(
                "--confirm-network is required to run the provider coverage "
                "CLI with --provider cifangquant"
            )
        return
    if provider_key == _AKSHARE_KEY:
        if not akshare_enabled:
            raise CoverageCLIConfigError(
                f"{_AKSHARE_ENABLED_ENV}=true is required to run the provider "
                "coverage CLI with --provider akshare; set it to acknowledge "
                "the real-API opt-in"
            )
        if not confirm_network:
            raise CoverageCLIConfigError(
                "--confirm-network is required to run the provider coverage "
                "CLI with --provider akshare"
            )
        return
    raise CoverageCLIConfigError(
        f"--provider {provider_key!r} is not supported by the coverage CLI; "
        f"expected {_FIXTURE_DEV_KEY!r}, {_CIFANG_KEY!r} or {_AKSHARE_KEY!r}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI.

    Exposed for tests so they can drive :func:`parse_args` without
    going through :data:`sys.argv`.
    """

    parser = argparse.ArgumentParser(
        prog="invest_pipeline.provider_coverage_cli",
        description=(
            "Read-only provider coverage CLI. Builds the deterministic "
            "source × symbol × date-range × field matrix using the V2 ETF "
            "Provider adapters. Default mode is offline (fixture_dev); "
            "--provider cifangquant requires INVEST_PIPELINE_CIFANG_ENABLED=true "
            "and --confirm-network; --provider akshare requires "
            "INVEST_PIPELINE_AKSHARE_ENABLED=true and --confirm-network. The "
            "CLI never writes to PostgreSQL, never invokes Dagster assets and "
            "never performs backfill."
        ),
    )
    parser.add_argument(
        "--provider",
        required=False,
        default=None,
        choices=(_FIXTURE_DEV_KEY, _CIFANG_KEY, _AKSHARE_KEY),
        help=(
            "Provider key to probe. Defaults to "
            f"{_PROVIDER_KEY_ENV} (fallback fixture_dev). Supported keys are "
            f"{_FIXTURE_DEV_KEY!r}, {_CIFANG_KEY!r} and {_AKSHARE_KEY!r}; "
            f"{_CIFANG_KEY!r} and {_AKSHARE_KEY!r} require their explicit "
            "environment opt-in plus --confirm-network."
        ),
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help=(
            f"Comma-separated ETF symbols to probe (1..{_MAX_SYMBOLS}, no "
            "duplicates). Example: 510300,510500,159919"
        ),
    )
    parser.add_argument(
        "--start-date",
        required=False,
        default=None,
        help=(
            "Inclusive start date for the probe window in YYYY-MM-DD. "
            "Defaults to 2026-07-23 (fixture_dev window) when omitted."
        ),
    )
    parser.add_argument(
        "--end-date",
        required=False,
        default=None,
        help=(
            "Inclusive end date for the probe window in YYYY-MM-DD. "
            "Defaults to 2026-07-30 (fixture_dev window) when omitted."
        ),
    )
    parser.add_argument(
        "--dataset",
        required=False,
        default=_DAILY_BARS_DATASET_KEY,
        choices=(_DAILY_BARS_DATASET_KEY,),
        help=(
            "Dataset to probe. Only etf_daily_bars is admitted in this slice; "
            "the field-completeness contract is the canonical OHLCV surface."
        ),
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help=(
            "Explicit opt-in to hit a real provider. Required only when "
            f"--provider is {_CIFANG_KEY!r} or {_AKSHARE_KEY!r} (combined "
            "with the matching enabled environment flag); ignored for "
            f"{_FIXTURE_DEV_KEY!r}."
        ),
    )
    parser.add_argument(
        "--generated-at",
        required=False,
        default=None,
        help=(
            "Optional ISO-8601 timestamp to stamp on the report. Defaults to "
            "the current UTC time; the deterministic content_hash is computed "
            "without it so two runs from the same probes still match."
        ),
    )
    return parser


@dataclass(frozen=True, slots=True)
class ProviderCoverageRunner:
    """Drives the bounded probe loop and builds the deterministic report.

    The runner is intentionally a pure orchestration object: it accepts
    a :class:`_CoverageProviderPort` (real or stub), invokes
    ``fetch_daily_bars`` once per symbol with the requested window,
    converts the resulting :class:`ProviderAttempt` / :class:`ProviderBatch`
    triples into :class:`_ProbeResult` bundles, and feeds the bundles
    into :func:`build_coverage_report_model` to produce the rich,
    deterministic :class:`CoverageReportModel`.

    The runner never writes to PostgreSQL, never invokes Dagster
    assets and never performs backfill; it closes the provider on
    every post-construction path so a misconfigured run cannot leak an
    open socket.
    """

    start_date: date
    end_date: date
    symbols: tuple[str, ...]
    provider: _CoverageProviderPort
    requested_fields: tuple[str, ...] = field(default_factory=default_daily_bars_field_set)
    generated_at: str | None = None

    def run(self) -> CoverageReportModel:
        samples_by_symbol: dict[str, list[DateRangeSample]] = {
            symbol: [] for symbol in self.symbols
        }
        record_counts: dict[str, dict[str, int]] = {}
        raw_payload_hashes: dict[str, str | None] = {}
        warnings_map: dict[str, dict[str, list[Any]]] = {}
        errors_map: dict[str, dict[str, list[Any]]] = {}

        symbols = list(self.symbols)
        per_symbol_record_counts: dict[str, int] = {symbol: 0 for symbol in symbols}
        per_symbol_warnings: dict[str, list[Any]] = {symbol: [] for symbol in symbols}
        per_symbol_errors: dict[str, list[Any]] = {symbol: [] for symbol in symbols}

        for symbol in symbols:
            try:
                request, attempt, batch = self.provider.fetch_daily_bars(
                    symbols=[symbol],
                    start_date=self.start_date,
                    end_date=self.end_date,
                )
            except RealProviderRequiresExplicitEnablementError as exc:
                per_symbol_errors[symbol].append(
                    CoverageError(
                        provider_key=self.provider.provider_key,
                        symbol=symbol,
                        code="real_provider_disabled",
                        message=str(exc),
                    )
                )
                continue
            except ProviderError as exc:
                per_symbol_errors[symbol].append(
                    CoverageError(
                        provider_key=self.provider.provider_key,
                        symbol=symbol,
                        code=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue

            result = _attempt_to_probe_result(
                provider_key=self.provider.provider_key,
                symbol=symbol,
                start_date=self.start_date,
                end_date=self.end_date,
                attempt=attempt,
                batch=batch,
                request=request,
            )
            if result.batch_status is not None and result.record_count > 0:
                samples_by_symbol[symbol].append(
                    DateRangeSample(
                        start_date=self.start_date,
                        end_date=self.end_date,
                        fields=frozenset(self.requested_fields),
                    )
                )
            raw_payload_hashes[self.provider.provider_key] = result.raw_payload_hash
            per_symbol_record_counts[symbol] = result.record_count
            per_symbol_warnings[symbol].extend(
                CoverageWarning(
                    provider_key=result.provider_key,
                    symbol=result.symbol,
                    message=warning,
                )
                for warning in result.warnings
            )
            if result.error_code is not None and result.error_message is not None:
                per_symbol_errors[symbol].append(
                    CoverageError(
                        provider_key=result.provider_key,
                        symbol=result.symbol,
                        code=result.error_code,
                        message=result.error_message,
                    )
                )

        coverage = calculate_coverage(
            {
                self.provider.provider_key: {
                    symbol: tuple(samples_by_symbol[symbol]) for symbol in symbols
                }
            }
        )
        record_counts[self.provider.provider_key] = per_symbol_record_counts
        warnings_map[self.provider.provider_key] = per_symbol_warnings
        errors_map[self.provider.provider_key] = per_symbol_errors

        return build_coverage_report_model(
            coverage=coverage,
            requested_start=self.start_date,
            requested_end=self.end_date,
            requested_fields=self.requested_fields,
            generated_at=self.generated_at,
            record_counts=record_counts,
            raw_payload_hashes=raw_payload_hashes,
            warnings=warnings_map,
            errors=errors_map,
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.provider.close()

    @classmethod
    def from_active_instruments(
        cls,
        *,
        start_date: date,
        end_date: date,
        instruments: Iterable[Instrument],
        provider: _CoverageProviderPort,
        requested_fields: tuple[str, ...] | None = None,
        generated_at: str | None = None,
    ) -> ProviderCoverageRunner:
        """Build a runner whose ``symbols`` is the active ETF universe.

        The bridge delegates the universe resolution to
        :func:`invest_pipeline.provider_coverage_plan.select_active_etf_symbols`
        so the runner and the rest of the coverage pipeline share one
        definition of "active domestic ETF": instrument kind is ``ETF``,
        ``is_active`` is true, lifecycle status is ``ACTIVE`` and the
        exchange is one of ``SSE`` / ``SZSE``. The helper returns a
        sorted, deduplicated tuple of symbols; when a symbol appears on
        more than one exchange the helper raises
        :class:`invest_pipeline.provider_coverage_plan.ActiveUniverseAmbiguityError`
        and the classmethod re-raises it untouched so callers see the
        cross-exchange ambiguity without any silent fallback. An empty
        ``instruments`` iterable yields an empty-symbol runner.

        The runner forwards its ``start_date`` / ``end_date`` window to
        the helper so the universe is also intersected with the probe
        range: instruments listed after ``end_date`` or delisted before
        ``start_date`` are excluded so coverage probing never asks a
        Provider about a listing that did not exist during the window.
        """

        symbols = select_active_etf_symbols(
            instruments,
            start_date=start_date,
            end_date=end_date,
        )
        if requested_fields is None:
            requested_fields = default_daily_bars_field_set()
        return cls(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            provider=provider,
            requested_fields=requested_fields,
            generated_at=generated_at,
        )


def _attempt_to_probe_result(
    *,
    provider_key: str,
    symbol: str,
    start_date: date,
    end_date: date,
    attempt: ProviderAttempt,
    batch: ProviderBatch[DailyBar] | None,
    request: ProviderRequest,
) -> _ProbeResult:
    """Translate one (request, attempt, batch) triple into a :class:`_ProbeResult`."""

    if batch is None:
        return _ProbeResult(
            provider_key=provider_key,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            attempt_status=attempt.status,
            batch_status=None,
            record_count=0,
            raw_payload_hash=None,
            warnings=(),
            error_code=(
                None
                if attempt.status is not ProviderAttemptStatus.FAILED
                else (attempt.error_code or "attempt_failed")
            ),
            error_message=(
                None
                if attempt.status is not ProviderAttemptStatus.FAILED
                else attempt.error_message
            ),
            error_stage=(
                None
                if attempt.status is not ProviderAttemptStatus.FAILED
                else attempt.error_stage
            ),
        )

    matched_records = [
        bar
        for bar in batch.records
        if bar.trade_date >= start_date and bar.trade_date <= end_date
    ]
    record_count = len(matched_records)
    return _ProbeResult(
        provider_key=provider_key,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        attempt_status=attempt.status,
        batch_status=batch.status,
        record_count=record_count,
        raw_payload_hash=batch.raw_payload_hash,
        warnings=tuple(batch.warnings),
        error_code=None,
        error_message=None,
        error_stage=None,
    )


def run_coverage(
    runner: ProviderCoverageRunner,
    *,
    stdout,
    stderr,
    token: str = "",
) -> int:
    """Drive the probe runner and emit the redacted coverage report.

    Returns ``0`` on success, ``2`` when the runner is misconfigured
    (the caller never reached the network in that case), and ``1``
    when the runner itself raises an unexpected exception. The
    provider is closed on every post-construction path; the
    serialised report is written to ``stdout`` exactly once on
    success.
    """

    def _scrub_line(message: str) -> str:
        return _scrub(message, token)

    try:
        report = runner.run()
    except CoverageReportBuildError as exc:
        print(
            f"error: failed to build coverage report: {_scrub_line(str(exc))}",
            file=stderr,
        )
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"error: coverage probe failed: {type(exc).__name__}",
            file=stderr,
        )
        return 1
    finally:
        runner.close()

    try:
        line = serialize_coverage_report(report)
    except (TypeError, ValueError) as exc:
        print(
            f"error: failed to serialise coverage report: {type(exc).__name__}",
            file=stderr,
        )
        return 1
    print(line, file=stdout)
    return 0


def _build_provider(
    *,
    provider_key: str,
    cifang_settings: CifangSettings | None = None,
    akshare_settings: AkshareSettings | None = None,
) -> _CoverageProviderPort:
    """Construct the configured provider via the runtime factory.

    Tests inject a stub provider directly; production callers use the
    factory so the documented provider settings are honoured exactly once.
    """

    if provider_key == _FIXTURE_DEV_KEY:
        from invest_pipeline.adapters.fixture_dev.adapter import (
            FixtureDevInstrumentProvider,
        )

        return FixtureDevInstrumentProvider()
    if provider_key == _CIFANG_KEY:
        from invest_pipeline.config import Settings

        settings = Settings(provider_key=_CIFANG_KEY)
        return build_provider(
            settings,
            cifang_settings=cifang_settings,
        )
    if provider_key == _AKSHARE_KEY:
        from invest_pipeline.config import Settings

        settings = Settings(provider_key=_AKSHARE_KEY)
        return build_provider(
            settings,
            akshare_settings=akshare_settings,
        )
    raise CoverageCLIConfigError(
        f"--provider {provider_key!r} is not supported by the coverage CLI"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Mirrors the contract on the module docstring: returns a non-zero
    exit code and a concise ``refused:`` / ``error:`` line on stderr
    whenever any opt-in or input is missing, and returns ``0`` with a
    deterministic JSON report on success. The function never prints
    the API key, the raw payload, headers, exception reprs or full
    URLs.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = sys.stdout
    stderr = sys.stderr

    today = datetime.now(UTC).date()

    try:
        symbols = parse_symbols(args.symbols)
    except CoverageCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    try:
        start_date = parse_iso_date(
            args.start_date, field_name="start-date", today=today
        )
        end_date = parse_iso_date(
            args.end_date, field_name="end-date", today=today
        )
        start_date, end_date = validate_range(
            start_date=start_date,
            end_date=end_date,
            today=today,
        )
    except CoverageCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    if args.dataset != _DAILY_BARS_DATASET_KEY:
        print(
            f"error: --dataset {args.dataset!r} is not supported by the coverage "
            f"CLI; expected {_DAILY_BARS_DATASET_KEY!r}",
            file=stderr,
        )
        return 2

    try:
        provider_key = _resolve_provider_key(
            os.environ, explicit=args.provider
        )
    except CoverageCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    cifang_enabled_value = _cifang_enabled(os.environ)
    akshare_enabled_value = _akshare_enabled(os.environ)
    try:
        validate_provider_opt_in(
            provider_key=provider_key,
            cifang_enabled=cifang_enabled_value,
            confirm_network=args.confirm_network,
            akshare_enabled=akshare_enabled_value,
        )
    except CoverageCLIConfigError as exc:
        print(f"refused: {exc}", file=stderr)
        return 2

    cifang_settings_obj: CifangSettings | None = None
    akshare_settings_obj: AkshareSettings | None = None
    token = ""
    if provider_key == _CIFANG_KEY:
        token = _configured_cifang_token()
        try:
            cifang_settings_obj = CifangSettings()
        except Exception as exc:
            message = _scrub(str(exc), token)
            print(f"error: failed to load CifangSettings: {message}", file=stderr)
            return 2
    elif provider_key == _AKSHARE_KEY:
        token = _configured_akshare_token()
        try:
            akshare_settings_obj = AkshareSettings()
        except Exception as exc:
            message = _scrub(str(exc), token)
            print(f"error: failed to load AkshareSettings: {message}", file=stderr)
            return 2
        token = _configured_akshare_token(akshare_settings_obj)

    try:
        if provider_key == _AKSHARE_KEY:
            provider = _build_provider(
                provider_key=provider_key,
                cifang_settings=cifang_settings_obj,
                akshare_settings=akshare_settings_obj,
            )
        else:
            provider = _build_provider(
                provider_key=provider_key,
                cifang_settings=cifang_settings_obj,
            )
    except RealProviderRequiresExplicitEnablementError as exc:
        print(f"refused: {_scrub(str(exc), token)}", file=stderr)
        return 2
    except CoverageCLIConfigError as exc:
        print(f"error: {_scrub(str(exc), token)}", file=stderr)
        return 2
    except Exception as exc:
        print(f"error: failed to build provider: {type(exc).__name__}", file=stderr)
        return 2

    runner = ProviderCoverageRunner(
        start_date=start_date,
        end_date=end_date,
        symbols=tuple(symbols),
        provider=provider,
        requested_fields=default_daily_bars_field_set(),
        generated_at=args.generated_at,
    )
    return run_coverage(runner, stdout=stdout, stderr=stderr, token=token)


if __name__ == "__main__":
    raise SystemExit(main())
