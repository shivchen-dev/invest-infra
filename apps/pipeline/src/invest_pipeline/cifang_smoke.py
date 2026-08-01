"""Opt-in CifangQuant smoke command (ADR-0011, Phase 1).

Invoked as:

    python -m invest_pipeline.cifang_smoke \\
        --symbols 510300,510500 \\
        --trade-date 2026-07-30 \\
        --confirm-network

The smoke is intentionally safe-by-default:

- The real CifangQuant HTTP client is constructed only when **both**
  ``INVEST_PIPELINE_CIFANG_ENABLED=true`` (the
  :class:`CifangSettings.enabled` gate) and the explicit
  ``--confirm-network`` CLI flag are present. If either is missing the
  command exits non-zero with a concise message and never reaches the
  network.
- The API key is read only from the environment through
  :class:`CifangSettings` (the ``INVEST_PIPELINE_CIFANG_API_KEY`` env
  var) and is never accepted as a CLI argument and never printed.
- The command prints only a redacted JSON summary (provider key, trade
  date, instrument count, daily-bar count, batch status). It does
  **not** print the token, headers, raw payload, exception repr (which
  may embed secrets) or full URLs.
- It runs only the two adapter calls required for a minimal smoke:
  ``fetch_instruments(as_of=trade_date)`` and
  ``fetch_daily_bars(symbols, start_date=trade_date, end_date=trade_date)``.
  No data is persisted.

The corresponding Makefile target is ``provider-smoke``. See the
sibling CLI tests for the supported behaviour.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from invest_domain.instruments.models import Instrument
from invest_domain.market_data.models import (
    DailyBar,
    ProviderBatch,
    ProviderBatchStatus,
)

from invest_pipeline.adapters.cifang.adapter import CifangQuantInstrumentProvider
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    ProviderError,
    RealProviderRequiresExplicitEnablementError,
)

_MIN_SYMBOLS = 1
_MAX_SYMBOLS = 5


class SmokeConfigError(Exception):
    """Raised when the smoke configuration is incomplete or unsafe.

    The CLI translates this into a non-zero exit code (2) and a single
    short line on stderr. It is **not** a :class:`ProviderError`; the
    smoke never reaches the network when this is raised.
    """


class _SmokeProvider(Protocol):
    """Minimal duck-typed surface :func:`run_smoke` requires.

    Using a :class:`Protocol` keeps the smoke test-friendly: tests
    supply a stub that records calls and returns canned evidence
    bundles, while production uses the real
    :class:`CifangQuantInstrumentProvider`.
    """

    provider_key: str

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[object, object, ProviderBatch[Instrument] | None]: ...

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[object, object, ProviderBatch[DailyBar] | None]: ...

    def close(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI.

    Exposed for tests so they can drive ``parse_args`` without going
    through ``sys.argv``.
    """

    parser = argparse.ArgumentParser(
        prog="invest_pipeline.cifang_smoke",
        description=(
            "Opt-in smoke for the CifangQuant provider (ADR-0011). "
            "Requires INVEST_PIPELINE_CIFANG_ENABLED=true, "
            "INVEST_PIPELINE_CIFANG_API_KEY, and --confirm-network."
        ),
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help=(
            "Comma-separated symbols (1 to 5, no duplicates). "
            "Example: 510300,510500,159919"
        ),
    )
    parser.add_argument(
        "--trade-date",
        required=True,
        help=(
            "Single completed trading date in YYYY-MM-DD. "
            "Future dates are rejected."
        ),
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help=(
            "Required explicit confirmation that this run will hit the "
            "real CifangQuant API. The smoke refuses to start without it."
        ),
    )
    return parser


def parse_symbols(raw: str) -> list[str]:
    """Parse the ``--symbols`` value into a list of 1-5 unique symbols.

    Whitespace around each symbol is stripped; empty entries are
    rejected. The function is pure so unit tests can drive it with
    arbitrary strings without touching the environment.
    """

    if not isinstance(raw, str):
        raise SmokeConfigError("--symbols must be a string")
    parts = [segment.strip() for segment in raw.split(",")]
    if any(not segment for segment in parts):
        raise SmokeConfigError("--symbols must not contain empty entries")
    if len(parts) < _MIN_SYMBOLS or len(parts) > _MAX_SYMBOLS:
        raise SmokeConfigError(
            f"--symbols must contain between {_MIN_SYMBOLS} and "
            f"{_MAX_SYMBOLS} entries, got {len(parts)}"
        )
    if len(set(parts)) != len(parts):
        duplicates = sorted({symbol for symbol in parts if parts.count(symbol) > 1})
        raise SmokeConfigError(
            f"--symbols must not contain duplicates: {','.join(duplicates)}"
        )
    return parts


def parse_trade_date(raw: str, today: date) -> date:
    """Parse ``--trade-date`` into a :class:`date` and reject future dates."""

    if not isinstance(raw, str):
        raise SmokeConfigError("--trade-date must be a string")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise SmokeConfigError(
            f"--trade-date must be YYYY-MM-DD: {exc}"
        ) from exc
    if parsed > today:
        raise SmokeConfigError(
            f"--trade-date must not be in the future "
            f"(got {parsed.isoformat()}, today is {today.isoformat()})"
        )
    return parsed


def validate_opt_in(settings: CifangSettings, *, confirm_network: bool) -> None:
    """Reject the smoke unless every opt-in lever is on.

    The three checks are intentionally independent so the CLI message
    tells the operator exactly which lever is missing. The settings
    object is read only; this function never reaches the network.
    """

    if not settings.enabled:
        raise SmokeConfigError(
            "INVEST_PIPELINE_CIFANG_ENABLED=true is required to run the "
            "CifangQuant smoke; set it to acknowledge the real-API opt-in"
        )
    if not confirm_network:
        raise SmokeConfigError(
            "--confirm-network is required to run the CifangQuant smoke"
        )
    if not settings.api_key.get_secret_value():
        raise SmokeConfigError(
            "INVEST_PIPELINE_CIFANG_API_KEY is required to run the "
            "CifangQuant smoke"
        )


def build_summary(
    *,
    provider_key: str,
    trade_date: date,
    instrument_count: int,
    instrument_batch_status: ProviderBatchStatus,
    bar_count: int,
    bar_batch_status: ProviderBatchStatus,
) -> str:
    """Return a JSON-encoded, log/scrape-friendly summary line."""

    payload = {
        "provider_key": provider_key,
        "trade_date": trade_date.isoformat(),
        "instrument_count": instrument_count,
        "instrument_batch_status": instrument_batch_status.value,
        "daily_bar_count": bar_count,
        "daily_bar_batch_status": bar_batch_status.value,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def run_smoke(
    provider: _SmokeProvider,
    *,
    symbols: Sequence[str],
    trade_date: date,
    stdout,
    stderr,
    token: str = "",
) -> int:
    """Drive the two adapter calls and emit the redacted summary.

    Returns ``0`` on success, ``2`` when the adapter refuses
    enablement, and ``1`` for any other unrecoverable failure. The
    provider is closed on every post-construction path. Pass ``token``
    to scrub the API key out of any error text that may have leaked it
    into a Provider exception message; the Summary line on stdout
    never embeds the token regardless.
    """

    def _scrub(message: str) -> str:
        if not token:
            return message
        return message.replace(token, "***")

    try:
        try:
            _, _, instruments_batch = provider.fetch_instruments(trade_date)
        except RealProviderRequiresExplicitEnablementError as exc:
            print(f"refused: {_scrub(str(exc))}", file=stderr)
            return 2
        except ProviderError as exc:
            print(
                f"error: instruments fetch failed: {_scrub(str(exc))}",
                file=stderr,
            )
            return 1

        if instruments_batch is None:
            print(
                "error: instruments batch was empty (no batch returned)",
                file=stderr,
            )
            return 1
        if instruments_batch.status != ProviderBatchStatus.SUCCEEDED:
            print(
                "error: instruments batch status "
                f"{instruments_batch.status.value}",
                file=stderr,
            )
            return 1

        try:
            _, _, bars_batch = provider.fetch_daily_bars(
                symbols, trade_date, trade_date
            )
        except RealProviderRequiresExplicitEnablementError as exc:
            print(f"refused: {_scrub(str(exc))}", file=stderr)
            return 2
        except ProviderError as exc:
            print(
                f"error: daily bars fetch failed: {_scrub(str(exc))}",
                file=stderr,
            )
            return 1

        if bars_batch is None:
            print("error: daily bars batch was empty", file=stderr)
            return 1
        if bars_batch.status != ProviderBatchStatus.SUCCEEDED:
            print(
                f"error: daily bars batch status {bars_batch.status.value}",
                file=stderr,
            )
            return 1

        print(
            build_summary(
                provider_key=provider.provider_key,
                trade_date=trade_date,
                instrument_count=len(instruments_batch.records),
                instrument_batch_status=instruments_batch.status,
                bar_count=len(bars_batch.records),
                bar_batch_status=bars_batch.status,
            ),
            file=stdout,
        )
        return 0
    finally:
        # Closing the underlying httpx client is best-effort; never
        # let cleanup hide the real exit code.
        with contextlib.suppress(Exception):
            provider.close()


def _build_provider(
    settings: CifangSettings,
) -> CifangQuantInstrumentProvider:
    """Construct the real adapter for the CLI; tests inject a stub instead."""

    return CifangQuantInstrumentProvider(settings)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Mirrors the contract on the module docstring: returns a non-zero
    exit code and a concise message when any opt-in is missing, and
    returns ``0`` with a JSON summary on success. The function never
    prints the API key, the raw payload, or full URLs.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = sys.stdout
    stderr = sys.stderr

    try:
        symbols = parse_symbols(args.symbols)
        trade_date = parse_trade_date(args.trade_date, date.today())
    except SmokeConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    try:
        settings = CifangSettings()
    except Exception as exc:
        print(f"error: failed to load CifangSettings: {exc}", file=stderr)
        return 2

    try:
        validate_opt_in(settings, confirm_network=args.confirm_network)
    except SmokeConfigError as exc:
        print(f"refused: {exc}", file=stderr)
        return 2

    provider = _build_provider(settings)
    return run_smoke(
        provider,
        symbols=symbols,
        trade_date=trade_date,
        stdout=stdout,
        stderr=stderr,
        token=settings.api_key.get_secret_value(),
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SmokeConfigError",
    "build_parser",
    "build_summary",
    "main",
    "parse_symbols",
    "parse_trade_date",
    "run_smoke",
    "validate_opt_in",
]
