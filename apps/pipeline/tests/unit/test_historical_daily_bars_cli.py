"""Focused unit tests for the manual ``historical_daily_bars_backfill`` CLI.

The suite covers the bounded increment contract for the historical
ETF daily-bars backfill and the network-gate / redaction guarantees
preserved from the ADR-0011 ``--confirm-network`` convention:

* ``--start-date`` and ``--end-date`` are both required and validated
  as ``YYYY-MM-DD``; future dates and inverted ranges are rejected
  with a single ``error:`` line on stderr, and the CLI returns ``2``
  before ever importing or initialising the storage layer.
* The range validator additionally rejects ``end_date`` being in the
  future even when both endpoints parse individually.
* The chunker splits an inclusive ``[start_date, end_date]`` window
  into ``<= 90`` calendar-day slices whose union is the original
  range with no gap and no overlap; very short spans collapse to a
  single chunk.
* If the selected provider is ``cifangquant`` the CLI requires both
  ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and ``--confirm-network``;
  either alone is insufficient. ``--confirm-network`` alone never
  enables a real provider, and ``fixture_dev`` runs need neither.
* ``run_backfill`` invokes the injected ``_ChunkRunner`` exactly once
  per produced chunk, never reuses a chunk across multiple runs (the
  per-chunk raw write + upsert are bundled inside the runner), and
  uses the ``request_key`` the runner reports — i.e. the request_key
  the provider stamped on the persisted ``raw.provider_requests``
  row, not a separate CLI-invented key.
* Fail-closed behaviour: a chunk that raises (or whose
  ``attempt_status`` is not ``"succeeded"``) stops the run at the
  first failing chunk, returns a non-zero exit code, and emits a
  final summary carrying ``status="failed"`` and the failing chunk
  index.
* The CLI never echoes the Cifang API key in stdout or stderr; the
  redacted-JSON-per-chunk and final-summary builder never embeds the
  key, exception reprs or absolute filesystem paths.
* ``run_backfill`` never imports or invokes Dagster assets other than
  the daily-bars raw write and the daily-bars upsert. The test
  asserts this by spying on those two service-call surfaces and
  asserting every other ``invest_pipeline.assets.*`` is untouched.

The tests never start a real network call and never require a live
PostgreSQL; the chunk-runner protocol lets the suite stay hermetic.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from collections.abc import Sequence
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

from invest_pipeline import historical_daily_bars_cli as cli

_SECRET_TOKEN = "historical-daily-bars-secret-marker-do-not-print"
_REDACTED = "***"
_FAKE_TODAY = date(2026, 7, 31)

_FIXTURE_REQUEST_KEY_PREFIX = "daily-bars"


def _fake_request_key(
    symbols: Sequence[str], chunk_start: date, chunk_end: date
) -> str:
    """Mirror the request-key shape every adapter stamps on the request."""

    return (
        f"{_FIXTURE_REQUEST_KEY_PREFIX}-{chunk_start.isoformat()}-"
        f"{chunk_end.isoformat()}-{'/'.join(symbols)}"
    )


def _chunk_result(
    *,
    provider_key: str,
    chunk_start: date,
    chunk_end: date,
    symbols: Sequence[str],
    request_status: str = "succeeded",
    attempt_status: str = "succeeded",
    record_count: int = 0,
    upsert_inserted: int = 0,
    upsert_skipped: int = 0,
) -> cli._ChunkResult:
    """Build a :class:`_ChunkResult` carrying a "real" provider-produced key."""

    return cli._ChunkResult(
        provider_key=provider_key,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        request_key=_fake_request_key(symbols, chunk_start, chunk_end),
        request_id=uuid4(),
        attempt_id=uuid4(),
        batch_id=uuid4() if record_count else None,
        request_status=request_status,
        attempt_status=attempt_status,
        record_count=record_count,
        upsert_inserted=upsert_inserted,
        upsert_skipped=upsert_skipped,
    )


class ParseIsoDateTest(unittest.TestCase):
    """Pure parsing of ``--start-date`` / ``--end-date``."""

    def test_accepts_iso_date(self) -> None:
        self.assertEqual(
            cli.parse_iso_date("2026-01-01", field_name="start-date", today=_FAKE_TODAY),
            date(2026, 1, 1),
        )

    def test_accepts_today(self) -> None:
        self.assertEqual(
            cli.parse_iso_date("2026-07-31", field_name="end-date", today=_FAKE_TODAY),
            _FAKE_TODAY,
        )

    def test_rejects_future_date(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.parse_iso_date("2026-08-01", field_name="start-date", today=_FAKE_TODAY)
        self.assertIn("future", str(ctx.exception))
        self.assertIn("start-date", str(ctx.exception))

    def test_rejects_invalid_format(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.parse_iso_date("2026/07/30", field_name="end-date", today=_FAKE_TODAY)
        self.assertIn("YYYY-MM-DD", str(ctx.exception))
        self.assertIn("end-date", str(ctx.exception))

    def test_rejects_invalid_month(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError):
            cli.parse_iso_date("2026-13-30", field_name="end-date", today=_FAKE_TODAY)

    def test_rejects_non_string(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError):
            cli.parse_iso_date(20260101, field_name="end-date", today=_FAKE_TODAY)  # type: ignore[arg-type]


class ValidateRangeTest(unittest.TestCase):
    """``validate_range`` rejects inverted or future-spanning ranges."""

    def test_accepts_equal_dates(self) -> None:
        cli.validate_range(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            today=_FAKE_TODAY,
        )

    def test_accepts_historical_window(self) -> None:
        cli.validate_range(
            start_date=date(2016, 1, 1),
            end_date=date(2016, 12, 31),
            today=_FAKE_TODAY,
        )

    def test_rejects_inverted_range(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.validate_range(
                start_date=date(2016, 12, 31),
                end_date=date(2016, 1, 1),
                today=_FAKE_TODAY,
            )
        self.assertIn("start-date", str(ctx.exception))
        self.assertIn("end-date", str(ctx.exception))

    def test_rejects_future_end_date(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError):
            cli.validate_range(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 8, 1),
                today=_FAKE_TODAY,
            )


class ChunkDateRangeTest(unittest.TestCase):
    """``chunk_date_range`` walks an inclusive window in <=90-day slices."""

    def test_single_day_window_produces_single_chunk(self) -> None:
        chunks = cli.chunk_date_range(date(2016, 1, 1), date(2016, 1, 1))
        self.assertEqual(chunks, [(date(2016, 1, 1), date(2016, 1, 1))])

    def test_one_year_splits_into_five_ninety_day_chunks(self) -> None:
        chunks = cli.chunk_date_range(date(2016, 1, 1), date(2016, 12, 31))
        self.assertEqual(len(chunks), 5)
        # Each chunk covers at most 90 calendar days inclusive.
        for chunk_start, chunk_end in chunks:
            self.assertGreaterEqual(chunk_end, chunk_start)
            self.assertLessEqual(
                (chunk_end - chunk_start).days + 1, 90
            )
        # Chunks are contiguous and cover the original window exactly.
        self.assertEqual(chunks[0][0], date(2016, 1, 1))
        self.assertEqual(chunks[-1][1], date(2016, 12, 31))
        for index in range(len(chunks) - 1):
            expected_next_start = chunks[index][1] + timedelta(days=1)
            self.assertEqual(chunks[index + 1][0], expected_next_start)

    def test_short_window_produces_one_chunk(self) -> None:
        chunks = cli.chunk_date_range(date(2016, 3, 1), date(2016, 4, 1))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], (date(2016, 3, 1), date(2016, 4, 1)))

    def test_exact_ninety_day_window_is_a_single_chunk(self) -> None:
        chunks = cli.chunk_date_range(date(2016, 1, 1), date(2016, 3, 30))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], (date(2016, 1, 1), date(2016, 3, 30)))

    def test_rejects_inverted_window(self) -> None:
        with self.assertRaises(ValueError):
            cli.chunk_date_range(date(2016, 12, 31), date(2016, 1, 1))

    def test_rejects_non_positive_max_days(self) -> None:
        with self.assertRaises(ValueError):
            cli.chunk_date_range(date(2016, 1, 1), date(2016, 1, 2), max_days=0)


class ValidateProviderOptInTest(unittest.TestCase):
    """Real provider opt-in never activates from the flag alone."""

    def test_fixture_dev_does_not_require_confirm_network(self) -> None:
        cli.validate_provider_opt_in(
            provider_key="fixture_dev",
            cifang_enabled=False,
            confirm_network=False,
        )

    def test_cifangquant_without_env_is_refused_even_with_confirm(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.validate_provider_opt_in(
                provider_key="cifangquant",
                cifang_enabled=False,
                confirm_network=True,
            )
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", str(ctx.exception))

    def test_cifangquant_without_confirm_is_refused_even_with_env(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.validate_provider_opt_in(
                provider_key="cifangquant",
                cifang_enabled=True,
                confirm_network=False,
            )
        self.assertIn("--confirm-network", str(ctx.exception))

    def test_cifangquant_with_both_opt_ins_passes(self) -> None:
        cli.validate_provider_opt_in(
            provider_key="cifangquant",
            cifang_enabled=True,
            confirm_network=True,
        )

    def test_unknown_provider_is_refused(self) -> None:
        with self.assertRaises(cli.HistoricalDailyBarsCLIConfigError) as ctx:
            cli.validate_provider_opt_in(
                provider_key="bogus",
                cifang_enabled=True,
                confirm_network=True,
            )
        self.assertIn("not supported", str(ctx.exception))
        self.assertIn("fixture_dev", str(ctx.exception))
        self.assertIn("cifangquant", str(ctx.exception))


class BuildEnvOverridesTest(unittest.TestCase):
    """``--universe`` is mapped to the documented env var only when set."""

    def test_returns_empty_when_no_overrides(self) -> None:
        self.assertEqual(cli.build_env_overrides(), {})

    def test_universe_maps_to_personal_universe_env(self) -> None:
        overrides = cli.build_env_overrides(universe="/tmp/u.yaml")
        self.assertEqual(
            overrides,
            {"INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": "/tmp/u.yaml"},
        )

    def test_empty_strings_are_dropped(self) -> None:
        self.assertEqual(cli.build_env_overrides(universe=""), {})


class BuildSummariesTest(unittest.TestCase):
    """The JSON summaries only carry safe, redacted fields."""

    def test_chunk_summary_carries_provider_key_and_request_key(self) -> None:
        result = _chunk_result(
            provider_key="fixture_dev",
            chunk_start=date(2016, 1, 1),
            chunk_end=date(2016, 3, 30),
            symbols=("510300", "510500"),
            record_count=42,
            upsert_inserted=42,
            upsert_skipped=0,
        )
        line = cli.build_chunk_summary(result, chunk_index=1)
        payload = json.loads(line)
        self.assertEqual(
            set(payload.keys()),
            {
                "chunk_index",
                "chunk_start",
                "chunk_end",
                "provider",
                "request_key",
                "request_id",
                "attempt_id",
                "batch_id",
                "request_status",
                "attempt_status",
                "record_count",
                "upsert_inserted",
                "upsert_skipped",
                "status",
            },
        )
        self.assertEqual(payload["chunk_index"], 1)
        self.assertEqual(payload["chunk_start"], "2016-01-01")
        self.assertEqual(payload["chunk_end"], "2016-03-30")
        self.assertEqual(payload["provider"], "fixture_dev")
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["record_count"], 42)
        self.assertEqual(payload["upsert_inserted"], 42)
        self.assertTrue(payload["request_key"].startswith("daily-bars-"))
        self.assertNotIn(_SECRET_TOKEN, line)

    def test_chunk_summary_marks_failed_attempt_status(self) -> None:
        result = _chunk_result(
            provider_key="fixture_dev",
            chunk_start=date(2016, 1, 1),
            chunk_end=date(2016, 3, 30),
            symbols=("510300",),
            request_status="failed",
            attempt_status="failed",
        )
        line = cli.build_chunk_summary(result, chunk_index=2)
        payload = json.loads(line)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["attempt_status"], "failed")
        self.assertEqual(payload["chunk_index"], 2)
        self.assertNotIn(_SECRET_TOKEN, line)

    def test_final_summary_carries_totals_and_failure_index(self) -> None:
        line = cli.build_final_summary(
            provider_key="fixture_dev",
            start_date=date(2016, 1, 1),
            end_date=date(2016, 12, 31),
            universe_count=7,
            total_chunks=5,
            completed_chunks=2,
            failed_chunk_index=3,
            status="failed",
            inserted_total=10,
            skipped_total=2,
        )
        payload = json.loads(line)
        self.assertEqual(
            set(payload.keys()),
            {
                "provider",
                "start_date",
                "end_date",
                "universe_count",
                "total_chunks",
                "completed_chunks",
                "failed_chunk_index",
                "status",
                "inserted_total",
                "skipped_total",
            },
        )
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failed_chunk_index"], 3)
        self.assertEqual(payload["completed_chunks"], 2)
        self.assertNotIn(_SECRET_TOKEN, line)

    def test_final_summary_does_not_echo_api_key_marker(self) -> None:
        line = cli.build_final_summary(
            provider_key="cifangquant",
            start_date=date(2016, 1, 1),
            end_date=date(2016, 12, 31),
            universe_count=5,
            total_chunks=5,
            completed_chunks=5,
            failed_chunk_index=None,
            status="succeeded",
            inserted_total=100,
            skipped_total=10,
        )
        self.assertNotIn("api_key", line)
        self.assertNotIn("INVEST_PIPELINE_CIFANG_API_KEY", line)


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

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._stdout_patch.__exit__(exc_type, exc, tb)
        self._stderr_patch.__exit__(exc_type, exc, tb)


class _RecorderChunkRunner:
    """Stand-in :class:`_ChunkRunner` recording every call.

    Tests inject canned ``results`` keyed by ``(start, end)`` so the
    runner can drive pass-through, failure and request-mismatch
    scenarios without ever opening a database. ``run_chunk`` is
    guaranteed to be called once per produced chunk in
    :func:`cli.run_backfill`.
    """

    def __init__(
        self,
        *,
        provider_key: str = "fixture_dev",
        results: list[cli._ChunkResult] | None = None,
        errors: list[BaseException] | None = None,
    ) -> None:
        self._provider_key = provider_key
        self._results = list(results or [])
        self._errors = list(errors or [])
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    @property
    def provider_key(self) -> str:
        return self._provider_key

    def run_chunk(
        self,
        *,
        symbols: Sequence[str],
        chunk_start: date,
        chunk_end: date,
    ) -> cli._ChunkResult:
        self.calls.append((tuple(symbols), chunk_start, chunk_end))
        if self._errors:
            raise self._errors.pop(0)
        if not self._results:
            raise AssertionError(
                "no canned result available for chunk "
                f"{chunk_start.isoformat()} -> {chunk_end.isoformat()}"
            )
        return self._results.pop(0)

    def close(self) -> None:
        return None


class RunBackfillTest(unittest.TestCase):
    """``run_backfill`` orchestrates the chunks, summaries and failure modes."""

    def test_walks_each_chunk_and_emits_one_summary_per_completion(self) -> None:
        chunks = cli.chunk_date_range(date(2016, 1, 1), date(2016, 3, 30))
        results = [
            _chunk_result(
                provider_key="fixture_dev",
                chunk_start=cs,
                chunk_end=ce,
                symbols=("510300",),
                record_count=2,
                upsert_inserted=2,
                upsert_skipped=0,
            )
            for cs, ce in chunks
        ]
        runner = _RecorderChunkRunner(results=results)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 0)
        # The runner is called exactly once per planned chunk.
        self.assertEqual(len(runner.calls), len(chunks))
        for (called_symbols, called_start, called_end), (expected_start, expected_end) in zip(
            runner.calls, chunks, strict=True
        ):
            self.assertEqual(called_symbols, ("510300",))
            self.assertEqual((called_start, called_end), (expected_start, expected_end))
        # One JSON line per chunk plus the final summary line.
        lines = [
            json.loads(line)
            for line in stdout.getvalue().splitlines()
            if line.startswith("{")
        ]
        self.assertEqual(len(lines), len(chunks) + 1)
        for index, line in enumerate(lines[:-1], start=1):
            self.assertEqual(line["chunk_index"], index)
        final = lines[-1]
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["completed_chunks"], len(chunks))
        self.assertEqual(final["failed_chunk_index"], None)
        self.assertEqual(final["inserted_total"], 2 * len(chunks))
        self.assertEqual(stderr.getvalue(), "")

    def test_uses_provider_produced_request_key_not_an_invented_one(self) -> None:
        """The runner gets to decide the request_key; the CLI must echo it.

        A successful chunk returns ``request_key="daily-bars-..."`` from
        the runner (i.e. the request_key the provider stamped on the
        persisted ``raw.provider_requests`` row). The CLI must emit
        that exact key in its summary instead of recomputing one
        locally, so the upsert line-up stays aligned with the raw
        write the runner performed.
        """

        expected_key = (
            "daily-bars-2016-01-01-2016-03-30-510300-510500-159915"
        )
        result = cli._ChunkResult(
            provider_key="fixture_dev",
            chunk_start=date(2016, 1, 1),
            chunk_end=date(2016, 3, 30),
            request_key=expected_key,
            request_id=uuid4(),
            attempt_id=uuid4(),
            batch_id=uuid4(),
            request_status="succeeded",
            attempt_status="succeeded",
            record_count=3,
            upsert_inserted=3,
            upsert_skipped=0,
        )
        runner = _RecorderChunkRunner(results=[result])
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300", "510500", "159915"),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 0)
        chunk_line = json.loads(stdout.getvalue().splitlines()[0])
        self.assertEqual(chunk_line["request_key"], expected_key)

    def test_stops_at_first_failed_attempt_and_reports_failed_chunk_index(
        self,
    ) -> None:
        chunks = cli.chunk_date_range(date(2016, 1, 1), date(2016, 6, 28))
        success = _chunk_result(
            provider_key="fixture_dev",
            chunk_start=chunks[0][0],
            chunk_end=chunks[0][1],
            symbols=("510300",),
            record_count=2,
            upsert_inserted=2,
            upsert_skipped=0,
        )
        failure = _chunk_result(
            provider_key="fixture_dev",
            chunk_start=chunks[1][0],
            chunk_end=chunks[1][1],
            symbols=("510300",),
            request_status="failed",
            attempt_status="failed",
        )
        runner = _RecorderChunkRunner(results=[success, failure])
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 6, 28),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 3)
        self.assertEqual(len(runner.calls), 2)
        # Stderr mentions the failing chunk index and the provider's failure.
        self.assertIn("chunk 2", stderr.getvalue())
        self.assertIn("attempt failed", stderr.getvalue())
        lines = [
            json.loads(line)
            for line in stdout.getvalue().splitlines()
            if line.startswith("{")
        ]
        self.assertEqual(len(lines), len(chunks) + 1)
        # The chunk summaries cover the chunks that actually ran.
        self.assertEqual(lines[0]["chunk_index"], 1)
        self.assertEqual(lines[0]["status"], "succeeded")
        # The chunk-2 entry carries the failed attempt_status.
        self.assertEqual(lines[1]["chunk_index"], 2)
        self.assertEqual(lines[1]["attempt_status"], "failed")
        # The final summary aggregates: 1 succeeded, 1 attempted, total = full plan.
        final = lines[-1]
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["completed_chunks"], 1)
        self.assertEqual(final["total_chunks"], len(chunks))
        self.assertEqual(final["failed_chunk_index"], 2)
        self.assertEqual(final["inserted_total"], 2)

    def test_lookup_error_fails_closed_with_exit_three(self) -> None:
        runner = _RecorderChunkRunner(
            errors=[LookupError("no successful request persisted")]
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 1, 1),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 3)
        self.assertIn("no successful request", stderr.getvalue())
        lines = [
            json.loads(line)
            for line in stdout.getvalue().splitlines()
            if line.startswith("{")
        ]
        final = lines[-1]
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["failed_chunk_index"], 1)
        self.assertEqual(final["completed_chunks"], 0)

    def test_rejects_empty_symbols_before_invoking_runner(self) -> None:
        runner = _RecorderChunkRunner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=(),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 2)
        self.assertIn("zero symbols", stderr.getvalue())
        self.assertEqual(runner.calls, [])

    def test_rejects_inverted_range_before_invoking_runner(self) -> None:
        runner = _RecorderChunkRunner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 12, 31),
            end_date=date(2016, 1, 1),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 2)
        self.assertIn("start-date", stderr.getvalue())
        self.assertEqual(runner.calls, [])


class TokenNonLeakTest(unittest.TestCase):
    """The CLI never echoes the supplied Cifang API key in stdout or stderr."""

    def _build_one_chunk_runner(self) -> _RecorderChunkRunner:
        return _RecorderChunkRunner(
            results=[
                _chunk_result(
                    provider_key="cifangquant",
                    chunk_start=date(2016, 1, 1),
                    chunk_end=date(2016, 3, 30),
                    symbols=("510300",),
                    record_count=1,
                    upsert_inserted=1,
                    upsert_skipped=0,
                )
            ]
        )

    def test_token_is_scrubbed_from_failure_message(self) -> None:
        class _TokenLeakingRunner:
            @property
            def provider_key(self) -> str:
                return "cifangquant"

            def run_chunk(
                self,
                *,
                symbols: Sequence[str],
                chunk_start: date,
                chunk_end: date,
            ) -> cli._ChunkResult:
                raise LookupError(f"missing persisted request: {_SECRET_TOKEN}")

        runner = _TokenLeakingRunner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,  # type: ignore[arg-type]
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertEqual(rc, 3)
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())

    def test_token_is_not_emitted_on_success_path(self) -> None:
        runner = self._build_one_chunk_runner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertEqual(rc, 0)
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())


class OnlyDailyBarsAssetsInvokedTest(unittest.TestCase):
    """``run_backfill`` only touches the daily-bars raw write + upsert.

    The other Dagster assets (``etf_instruments_raw``, ``etf_instruments``,
    ``etf_input_snapshot``, ``personal_candidate_pool``, etc.) must not
    be imported or invoked. The runner isolation lets the suite
    assert this directly without booting Dagster.
    """

    def test_main_refuses_to_invoke_dagster_assets(self) -> None:
        runner = _RecorderChunkRunner(
            results=[
                _chunk_result(
                    provider_key="fixture_dev",
                    chunk_start=date(2016, 1, 1),
                    chunk_end=date(2016, 3, 30),
                    symbols=("510300",),
                    record_count=1,
                    upsert_inserted=1,
                    upsert_skipped=0,
                )
            ]
        )

        assets = SimpleNamespace(
            etf_instruments_raw=mock.MagicMock(),
            etf_instruments=mock.MagicMock(),
            etf_daily_bars_raw=mock.MagicMock(),
            etf_input_snapshot=mock.MagicMock(),
            personal_candidate_pool=mock.MagicMock(),
            seed_instruments=mock.MagicMock(),
        )

        pre_definitions_entry = sys.modules.get("invest_pipeline.definitions")

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            _CaptureStdStreams() as (_stdout, _stderr),
            mock.patch.dict(
                "sys.modules",
                {
                    "invest_pipeline.assets": assets,
                    "invest_pipeline.definitions": mock.MagicMock(),
                },
            ),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner",
                return_value=runner,
            ),
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-01-01",
                    "--end-date",
                    "2016-03-30",
                ]
            )

        self.assertEqual(rc, 0)
        # Only the runner was called; no other asset import was triggered.
        for asset_name in (
            "etf_instruments_raw",
            "etf_instruments",
            "etf_input_snapshot",
            "personal_candidate_pool",
            "seed_instruments",
        ):
            getattr(assets, asset_name).assert_not_called()
        self.assertEqual(len(runner.calls), 1)
        # ``invest_pipeline.definitions`` must not have been newly imported by
        # this invocation. We snapshot the relevant ``sys.modules`` entry
        # before the call and assert it is unchanged after — that lets the
        # test stay order-independent when other suites load
        # ``invest_pipeline.definitions`` ahead of this one.
        self.assertIs(
            sys.modules.get("invest_pipeline.definitions"),
            pre_definitions_entry,
        )

    def test_run_backfill_does_not_import_dagster(self) -> None:
        runner = _RecorderChunkRunner(
            results=[
                _chunk_result(
                    provider_key="fixture_dev",
                    chunk_start=date(2016, 1, 1),
                    chunk_end=date(2016, 3, 30),
                    symbols=("510300",),
                    record_count=1,
                    upsert_inserted=1,
                    upsert_skipped=0,
                )
            ]
        )
        pre_dagster_entry = sys.modules.get("dagster")
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_backfill(
            runner=runner,
            symbols=("510300",),
            start_date=date(2016, 1, 1),
            end_date=date(2016, 3, 30),
            today=date(2026, 7, 31),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 0)
        # ``run_backfill`` must not pull Dagster into the interpreter as a
        # side effect of its own orchestration; the default runner is
        # responsible for any storage-layer import. Snapshot the
        # ``dagster`` entry of ``sys.modules`` so this assertion stays
        # order-independent when other suites have already imported it.
        self.assertIs(sys.modules.get("dagster"), pre_dagster_entry)


class EnvStackTest(unittest.TestCase):
    """``_EnvStack`` injects overrides and restores the prior values."""

    def test_apply_and_restore_universe(self) -> None:
        sentinel = "/tmp/custom-universe.yaml"
        previous = os.environ.get("INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH")
        try:
            with cli._EnvStack(
                {"INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": sentinel}
            ):
                self.assertEqual(
                    os.environ["INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"],
                    sentinel,
                )
            self.assertNotIn(
                "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH",
                os.environ,
            )
        finally:
            if previous is not None:
                os.environ["INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"] = previous

    def test_restore_does_not_clobber_when_key_unset(self) -> None:
        os.environ.pop("INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH", None)
        with cli._EnvStack(
            {"INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": "/tmp/p"}
        ):
            self.assertEqual(
                os.environ["INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"],
                "/tmp/p",
            )
        self.assertNotIn(
            "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH", os.environ
        )


class DefaultRunnerTest(unittest.TestCase):
    """``_DefaultChunkRunner`` wires raw write + upsert + request_key lookup."""

    def test_runner_uses_stored_request_key_for_upsert(self) -> None:
        """The default runner reads the persisted request_key back from
        storage and forwards it to ``upsert_etf_daily_bars`` verbatim.

        Test fakes stand in for the providers / UoW to keep the suite
        free of SQLAlchemy / Postgres: a fake raw-write returns a
        canned ``RawEtlResult``, a fake UoW returns the
        provider-produced ``request_key``, and a fake upsert service
        captures the ``request_key`` it was called with so the
        assertion can prove the default runner never re-invents it.
        """

        symbols = ("510300", "510500")
        chunk_start = date(2016, 1, 1)
        chunk_end = date(2016, 3, 30)
        expected_key = _fake_request_key(symbols, chunk_start, chunk_end)
        request_id = uuid4()
        attempt_id = uuid4()
        batch_id = uuid4()

        from invest_pipeline.etf_daily_bars import UpsertSummary
        from invest_pipeline.etf_instruments import RawEtlResult

        raw_result = RawEtlResult(
            request_id=request_id,
            attempt_id=attempt_id,
            batch_id=batch_id,
            request_status="succeeded",
            attempt_status="succeeded",
            record_count=2,
        )

        class _StubProvider:
            provider_key = "fixture_dev"

        captured_upsert_calls: list[dict[str, Any]] = []

        def _fake_upsert(
            session_factory: Any,
            *,
            provider_key: str,
            dataset_key: str,
            request_key: str,
            unit_of_work_factory: Any,
        ) -> UpsertSummary:
            captured_upsert_calls.append(
                {
                    "session_factory": session_factory,
                    "provider_key": provider_key,
                    "dataset_key": dataset_key,
                    "request_key": request_key,
                }
            )
            return UpsertSummary(inserted=2, skipped=0)

        class _StubStoredRequest:
            def __init__(self, request_key: str) -> None:
                self.request_key = request_key

        class _StubProviderRequestsRepo:
            def __init__(self, request_key: str) -> None:
                self._request_key = request_key

            def get_by_id(self, provider_request_id: UUID) -> _StubStoredRequest:
                return _StubStoredRequest(self._request_key)

        class _StubUoW:
            def __init__(self, session_factory: Any) -> None:
                self._session_factory = session_factory
                self.provider_requests = _StubProviderRequestsRepo(expected_key)

            def __enter__(self) -> _StubUoW:
                return self

            def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
                return None

        def _fake_uow_factory(session_factory: Any) -> _StubUoW:
            return _StubUoW(session_factory)

        session_factory = object()
        with mock.patch(
            "invest_pipeline.historical_daily_bars_cli.write_etf_daily_bars_raw",
            return_value=raw_result,
        ) as raw_spy, mock.patch(
            "invest_pipeline.historical_daily_bars_cli.upsert_etf_daily_bars",
            side_effect=_fake_upsert,
        ) as upsert_spy:
            runner = cli._DefaultChunkRunner(
                _StubProvider(),
                session_factory,
                unit_of_work_factory=_fake_uow_factory,
            )
            result = runner.run_chunk(
                symbols=symbols,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
            )

        self.assertEqual(result.request_key, expected_key)
        self.assertEqual(result.attempt_id, attempt_id)
        self.assertEqual(result.batch_id, batch_id)
        self.assertEqual(result.upsert_inserted, 2)
        self.assertEqual(result.upsert_skipped, 0)
        raw_spy.assert_called_once()
        upsert_spy.assert_called_once()
        # The default runner forwards the recovered request_key, not a
        # value it invented locally.
        self.assertEqual(len(captured_upsert_calls), 1)
        self.assertEqual(
            captured_upsert_calls[0]["request_key"], expected_key
        )
        self.assertEqual(
            captured_upsert_calls[0]["dataset_key"], "etf_daily_bars"
        )
        self.assertEqual(
            captured_upsert_calls[0]["provider_key"], "fixture_dev"
        )


class ParserTest(unittest.TestCase):
    """The argparse surface requires both dates and surfaces ``--confirm-network``."""

    def test_help_is_exposed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            cli.build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_requires_start_date(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(
                ["--end-date", "2016-12-31", "--confirm-network"]
            )

    def test_requires_end_date(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(
                ["--start-date", "2016-01-01", "--confirm-network"]
            )

    def test_confirm_network_is_optional(self) -> None:
        """``--confirm-network`` is gated by the provider check, not argparse."""

        parsed = cli.build_parser().parse_args(
            ["--start-date", "2016-01-01", "--end-date", "2016-12-31"]
        )
        self.assertFalse(parsed.confirm_network)


class MainRefusalTest(unittest.TestCase):
    """``main`` exits non-zero before ever touching storage on bad input."""

    def test_future_end_date_is_refused_without_touching_storage(self) -> None:
        with (
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner"
            ) as runner_spy,
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-01-01",
                    "--end-date",
                    "2030-01-01",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("future", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        runner_spy.assert_not_called()

    def test_inverted_range_is_refused_without_touching_storage(self) -> None:
        with (
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner"
            ) as runner_spy,
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-12-31",
                    "--end-date",
                    "2016-01-01",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("start-date", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        runner_spy.assert_not_called()

    def test_cifangquant_without_env_is_refused(self) -> None:
        env = {"INVEST_PIPELINE_PROVIDER_KEY": "cifangquant"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner"
            ) as runner_spy,
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-01-01",
                    "--end-date",
                    "2016-12-31",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", stderr.getvalue())
        runner_spy.assert_not_called()

    def test_cifangquant_without_confirm_is_refused(self) -> None:
        env = {
            "INVEST_PIPELINE_PROVIDER_KEY": "cifangquant",
            "INVEST_PIPELINE_CIFANG_ENABLED": "true",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner"
            ) as runner_spy,
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-01-01",
                    "--end-date",
                    "2016-12-31",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-network", stderr.getvalue())
        runner_spy.assert_not_called()

    def test_unknown_provider_is_refused(self) -> None:
        env = {"INVEST_PIPELINE_PROVIDER_KEY": "bogus"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.historical_daily_bars_cli._build_default_runner"
            ) as runner_spy,
        ):
            rc = cli.main(
                [
                    "--start-date",
                    "2016-01-01",
                    "--end-date",
                    "2016-12-31",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("not supported", stderr.getvalue())
        runner_spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
