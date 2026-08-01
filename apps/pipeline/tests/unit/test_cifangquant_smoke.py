"""Unit tests for the opt-in CifangQuant smoke CLI (ADR-0011, Phase 1).

The suite covers the contract from the bounded increment:

- Missing enablement flag (no real client is built).
- Missing ``--confirm-network`` flag.
- Missing API key.
- Symbol/date validation rules (1..5, no duplicates, no future).
- Happy path via a stub provider that records calls and returns
  canned evidence — no network, no real ``CifangClient``.
- Provider failure exits non-zero.
- API key is never echoed in stdout/stderr through the smoke output.

Every test is fully offline: it patches ``os.environ`` to control the
settings path and supplies a stub provider so the real adapter is
never instantiated.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from datetime import date
from typing import Any
from unittest import mock
from uuid import uuid4

from invest_domain.market_data.models import (
    ProviderBatch,
    ProviderBatchStatus,
)
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.cifang_smoke import (
    SmokeConfigError,
    build_parser,
    build_summary,
    main,
    parse_symbols,
    parse_trade_date,
    run_smoke,
    validate_opt_in,
)

_SECRET_TOKEN = "smoke-secret-token-do-not-print"
_OPT_IN_ENV = {
    "INVEST_PIPELINE_CIFANG_ENABLED": "true",
    "INVEST_PIPELINE_CIFANG_API_KEY": _SECRET_TOKEN,
}
_REDACTED = "***"
_FAKE_TODAY = date(2026, 7, 30)


def _make_batch(
    *,
    record_count: int,
    status: ProviderBatchStatus = ProviderBatchStatus.SUCCEEDED,
) -> ProviderBatch[Any]:
    """Return a :class:`ProviderBatch` with ``record_count`` placeholder rows."""

    return ProviderBatch[Any](
        attempt_id=uuid4(),
        records=tuple(object() for _ in range(record_count)),
        raw_payload_hash="a" * 64,
        status=status,
    )


class _StubProvider:
    """Stub adapter that records calls and returns canned evidence.

    The stub satisfies the smoke ``_SmokeProvider`` protocol without
    touching the real ``CifangClient`` / httpx transport.
    """

    def __init__(
        self,
        *,
        instruments_batch: ProviderBatch[Any] | None = None,
        instruments_error: Exception | None = None,
        bars_batch: ProviderBatch[Any] | None = None,
        bars_error: Exception | None = None,
        provider_key: str = "cifangquant",
    ) -> None:
        self.provider_key = provider_key
        self._instruments_batch = instruments_batch
        self._instruments_error = instruments_error
        self._bars_batch = bars_batch
        self._bars_error = bars_error
        self.instruments_calls: list[date] = []
        self.bars_calls: list[tuple[tuple[str, ...], date, date]] = []
        self.close_calls = 0

    def fetch_instruments(self, as_of: date):
        self.instruments_calls.append(as_of)
        if self._instruments_error is not None:
            raise self._instruments_error
        return None, None, self._instruments_batch

    def fetch_daily_bars(self, symbols, start_date, end_date):
        self.bars_calls.append((tuple(symbols), start_date, end_date))
        if self._bars_error is not None:
            raise self._bars_error
        return None, None, self._bars_batch

    def close(self) -> None:
        self.close_calls += 1


class ParseSymbolsTest(unittest.TestCase):
    """Pure parsing of the ``--symbols`` value."""

    def test_accepts_one_to_five_symbols(self) -> None:
        self.assertEqual(parse_symbols("510300"), ["510300"])
        self.assertEqual(
            parse_symbols("510300,510500,159919,510330,510880"),
            ["510300", "510500", "159919", "510330", "510880"],
        )

    def test_strips_whitespace(self) -> None:
        self.assertEqual(parse_symbols(" 510300 , 510500,159919 "), ["510300", "510500", "159919"])

    def test_rejects_empty_entries(self) -> None:
        for raw in ("510300,,510500", ",510300", "510300, "):
            with self.subTest(raw=raw), self.assertRaises(SmokeConfigError) as ctx:
                parse_symbols(raw)
            self.assertIn("empty", str(ctx.exception))

    def test_rejects_empty_input(self) -> None:
        for empty in ("", "   ", ",,,"):
            with self.subTest(empty=empty), self.assertRaises(SmokeConfigError):
                parse_symbols(empty)

    def test_rejects_more_than_five_symbols(self) -> None:
        with self.assertRaises(SmokeConfigError) as ctx:
            parse_symbols("1,2,3,4,5,6")
        self.assertIn("between 1 and 5", str(ctx.exception))

    def test_rejects_duplicate_symbols(self) -> None:
        with self.assertRaises(SmokeConfigError) as ctx:
            parse_symbols("510300,510500,510300")
        self.assertIn("duplicate", str(ctx.exception))
        self.assertIn("510300", str(ctx.exception))


class ParseTradeDateTest(unittest.TestCase):
    """Pure parsing of the ``--trade-date`` value."""

    def test_accepts_iso_date(self) -> None:
        self.assertEqual(
            parse_trade_date("2026-07-30", _FAKE_TODAY),
            date(2026, 7, 30),
        )

    def test_accepts_today(self) -> None:
        self.assertEqual(parse_trade_date("2026-07-30", _FAKE_TODAY), _FAKE_TODAY)

    def test_rejects_future_date(self) -> None:
        with self.assertRaises(SmokeConfigError) as ctx:
            parse_trade_date("2026-07-31", _FAKE_TODAY)
        self.assertIn("future", str(ctx.exception))

    def test_rejects_invalid_format(self) -> None:
        with self.assertRaises(SmokeConfigError) as ctx:
            parse_trade_date("2026/07/30", _FAKE_TODAY)
        self.assertIn("YYYY-MM-DD", str(ctx.exception))

    def test_rejects_invalid_month(self) -> None:
        with self.assertRaises(SmokeConfigError):
            parse_trade_date("2026-13-30", _FAKE_TODAY)

    def test_rejects_non_string(self) -> None:
        with self.assertRaises(SmokeConfigError):
            parse_trade_date(20260730, _FAKE_TODAY)  # type: ignore[arg-type]


class ValidateOptInTest(unittest.TestCase):
    """The opt-in gate must catch every missing lever."""

    def test_rejects_when_disabled(self) -> None:
        settings = CifangSettings()
        with self.assertRaises(SmokeConfigError) as ctx:
            validate_opt_in(settings, confirm_network=True)
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", str(ctx.exception))

    def test_rejects_without_confirm_network(self) -> None:
        settings = CifangSettings()
        object.__setattr__(settings, "enabled", True)
        with self.assertRaises(SmokeConfigError) as ctx:
            validate_opt_in(settings, confirm_network=False)
        self.assertIn("--confirm-network", str(ctx.exception))

    def test_rejects_without_api_key(self) -> None:
        settings = CifangSettings()
        object.__setattr__(settings, "enabled", True)
        with self.assertRaises(SmokeConfigError) as ctx:
            validate_opt_in(settings, confirm_network=True)
        self.assertIn("INVEST_PIPELINE_CIFANG_API_KEY", str(ctx.exception))

    def test_passes_when_all_enabled(self) -> None:
        settings = CifangSettings(api_key="some-token")
        object.__setattr__(settings, "enabled", True)
        # Should not raise.
        validate_opt_in(settings, confirm_network=True)


class BuildSummaryTest(unittest.TestCase):
    """The summary is the only thing the smoke prints on success."""

    def test_summary_is_json_with_required_keys(self) -> None:
        line = build_summary(
            provider_key="cifangquant",
            trade_date=date(2026, 7, 30),
            instrument_count=12,
            instrument_batch_status=ProviderBatchStatus.SUCCEEDED,
            bar_count=5,
            bar_batch_status=ProviderBatchStatus.SUCCEEDED,
        )
        payload = json.loads(line)
        self.assertEqual(
            set(payload.keys()),
            {
                "provider_key",
                "trade_date",
                "instrument_count",
                "instrument_batch_status",
                "daily_bar_count",
                "daily_bar_batch_status",
            },
        )
        self.assertEqual(payload["provider_key"], "cifangquant")
        self.assertEqual(payload["trade_date"], "2026-07-30")
        self.assertEqual(payload["instrument_count"], 12)
        self.assertEqual(payload["daily_bar_count"], 5)
        self.assertEqual(payload["instrument_batch_status"], "succeeded")
        self.assertEqual(payload["daily_bar_batch_status"], "succeeded")

    def test_summary_does_not_carry_token_field(self) -> None:
        line = build_summary(
            provider_key="cifangquant",
            trade_date=date(2026, 7, 30),
            instrument_count=0,
            instrument_batch_status=ProviderBatchStatus.SUCCEEDED,
            bar_count=0,
            bar_batch_status=ProviderBatchStatus.SUCCEEDED,
        )
        self.assertNotIn("token", line)
        self.assertNotIn("api_key", line)


class RunSmokeTest(unittest.TestCase):
    """``run_smoke`` drives the two adapter calls and emits the summary."""

    def test_prints_redacted_summary_on_success(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(record_count=2),
            bars_batch=_make_batch(record_count=5),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(stub.close_calls, 1)
        self.assertEqual(stub.instruments_calls, [date(2026, 7, 30)])
        self.assertEqual(
            stub.bars_calls,
            [(("510300",), date(2026, 7, 30), date(2026, 7, 30))],
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["instrument_count"], 2)
        self.assertEqual(payload["daily_bar_count"], 5)
        self.assertEqual(payload["trade_date"], "2026-07-30")
        self.assertEqual(payload["provider_key"], "cifangquant")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())

    def test_returns_nonzero_on_instruments_provider_error(self) -> None:
        stub = _StubProvider(
            instruments_error=ProviderAuthenticationError(
                "cifangquant", "HTTP 401 (auth)"
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("instruments fetch failed", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stub.close_calls, 1)

    def test_returns_nonzero_on_daily_bars_provider_error(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(record_count=2),
            bars_error=ProviderError("cifangquant", "boom"),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("daily bars fetch failed", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stub.close_calls, 1)

    def test_returns_nonzero_on_none_instruments_batch(self) -> None:
        stub = _StubProvider(
            instruments_batch=None,
            bars_batch=_make_batch(record_count=5),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("instruments batch was empty", stderr.getvalue())
        self.assertEqual(stub.close_calls, 1)

    def test_returns_nonzero_on_partial_instruments_batch(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(
                record_count=2,
                status=ProviderBatchStatus.PARTIAL,
            ),
            bars_batch=_make_batch(record_count=5),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("instruments batch status", stderr.getvalue())
        self.assertEqual(stub.close_calls, 1)

    def test_returns_nonzero_on_partial_bars_batch(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(record_count=2),
            bars_batch=_make_batch(
                record_count=5,
                status=ProviderBatchStatus.PARTIAL,
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("daily bars batch status", stderr.getvalue())
        self.assertEqual(stub.close_calls, 1)

    def test_returns_two_on_enablement_refusal(self) -> None:
        stub = _StubProvider(
            instruments_error=RealProviderRequiresExplicitEnablementError(
                "CifangQuant fetch_instruments requires CifangSettings.enabled=True"
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 2)
        self.assertIn("refused", stderr.getvalue())
        self.assertEqual(stub.close_calls, 1)

    def test_provider_is_closed_even_on_error(self) -> None:
        stub = _StubProvider(
            instruments_error=ProviderError("cifangquant", "boom"),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(stub.close_calls, 1)


class SecretNonLeakTest(unittest.TestCase):
    """The smoke must scrub the API key out of any captured output."""

    def test_secret_does_not_leak_in_success_output(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(record_count=2),
            bars_batch=_make_batch(record_count=5),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_secret_does_not_leak_when_error_message_embeds_token(self) -> None:
        stub = _StubProvider(
            instruments_error=ProviderError("cifangquant", _SECRET_TOKEN),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_smoke(
            stub,
            symbols=["510300"],
            trade_date=date(2026, 7, 30),
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertEqual(rc, 1)
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())
        # The redacted marker should appear in the scrubbed error text.
        self.assertIn(_REDACTED, stderr.getvalue())


class _CaptureStdStreams:
    """Redirect ``sys.stdout`` and ``sys.stderr`` for the duration of a block."""

    def __enter__(self) -> tuple[io.StringIO, io.StringIO]:
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()
        self._stdout_patch = mock.patch("sys.stdout", self._stdout)
        self._stderr_patch = mock.patch("sys.stderr", self._stderr)
        self._stdout_patch.__enter__()
        self._stderr_patch.__enter__()
        return self._stdout, self._stderr

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stdout_patch.__exit__(exc_type, exc, tb)
        self._stderr_patch.__exit__(exc_type, exc, tb)


class MainRefusalTest(unittest.TestCase):
    """``main`` must exit non-zero before reaching the network whenever
    the user has not opted in or supplied invalid input."""

    def test_main_returns_two_without_enablement(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(
            "INVEST_PIPELINE_CIFANG_"
        )}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300",
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_main_returns_two_without_confirm_network(self) -> None:
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300",
                    "--trade-date",
                    "2026-07-30",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-network", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_main_returns_two_without_api_key(self) -> None:
        env = {**_OPT_IN_ENV}
        env.pop("INVEST_PIPELINE_CIFANG_API_KEY")
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300",
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("INVEST_PIPELINE_CIFANG_API_KEY", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_main_returns_two_for_invalid_symbols(self) -> None:
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = main(
                [
                    "--symbols",
                    "1,2,3,4,5,6",
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("between 1 and 5", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_main_returns_two_for_invalid_date(self) -> None:
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300",
                    "--trade-date",
                    "2030-01-01",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("future", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())


class MainHappyPathTest(unittest.TestCase):
    """``main`` with a stubbed provider returns the redacted summary."""

    def test_main_returns_zero_with_stub_provider(self) -> None:
        stub = _StubProvider(
            instruments_batch=_make_batch(record_count=3),
            bars_batch=_make_batch(record_count=7),
        )
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.cifang_smoke._build_provider",
                return_value=stub,
            ),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300,510500",
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 0)
        self.assertEqual(stub.close_calls, 1)
        self.assertEqual(stub.instruments_calls, [date(2026, 7, 30)])
        self.assertEqual(
            stub.bars_calls,
            [
                (
                    ("510300", "510500"),
                    date(2026, 7, 30),
                    date(2026, 7, 30),
                )
            ],
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["instrument_count"], 3)
        self.assertEqual(payload["daily_bar_count"], 7)
        self.assertEqual(payload["trade_date"], "2026-07-30")
        self.assertEqual(payload["provider_key"], "cifangquant")
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_main_returns_one_when_provider_raises(self) -> None:
        stub = _StubProvider(
            instruments_error=ProviderAuthenticationError(
                "cifangquant", "HTTP 401 (auth)"
            ),
        )
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.cifang_smoke._build_provider",
                return_value=stub,
            ),
        ):
            rc = main(
                [
                    "--symbols",
                    "510300",
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("instruments fetch failed", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stub.close_calls, 1)


class ParserTest(unittest.TestCase):
    """Quick smoke on the argparse surface."""

    def test_help_is_exposed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
