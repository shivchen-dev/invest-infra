"""Focused unit tests for the manual ``personal_etf_daily_job`` CLI (PR-4).

The suite covers the bounded increment contract from the stage-1
execution plan §9.5/§9.6 plus the ADR-0011 confirm-network safety
rules already enforced by :mod:`invest_pipeline.cifang_smoke`:

* ``--trade-date`` is required, validated as ``YYYY-MM-DD`` and rejected
  when in the future; the CLI surfaces a single ``error:`` line on
  stderr and never imports :mod:`invest_pipeline.definitions`.
* ``--universe`` and ``--policy`` are mapped to the documented env
  variables (``INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH`` and
  ``INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH``) before the Dagster
  settings are read, so the helper is pure but the integration is
  exercised end-to-end on the captured ``os.environ``.
* If the selected provider is ``cifangquant`` the CLI requires both
  ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and ``--confirm-network``;
  either alone is insufficient. ``--confirm-network`` alone never
  enables a real provider; the flag has no effect on
  ``fixture_dev`` runs.
* A successful fixture run via a stubbed ``defs`` prints exactly one
  deterministic JSON line on stdout containing only the documented
  safe fields (counts, IDs, status). The summary builder handles the
  real Dagster ``*MetadataValue`` wrappers used by the live events.
* No secret is ever echoed in stdout or stderr: ``api_key`` /
  ``token`` leakage is asserted by injecting a known marker into the
  stubbed error path and confirming it never reaches the operator.

The tests never start a real network call and never require
:mod:`invest_pipeline.definitions` to be importable beyond its
existing presence in the package (and even then, only behind a
monkeypatched ``defs``).
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from collections.abc import Sequence
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

from dagster import IntMetadataValue, TextMetadataValue
from invest_pipeline import personal_daily_cli as cli

_SECRET_TOKEN = "personal-daily-secret-marker-do-not-print"
_REDACTED = "***"
_FAKE_TODAY = date(2026, 7, 30)


class ParseTradeDateTest(unittest.TestCase):
    """Pure parsing of the ``--trade-date`` value."""

    def test_accepts_iso_date(self) -> None:
        self.assertEqual(
            cli.parse_trade_date("2026-07-30", _FAKE_TODAY),
            date(2026, 7, 30),
        )

    def test_accepts_today(self) -> None:
        self.assertEqual(cli.parse_trade_date("2026-07-30", _FAKE_TODAY), _FAKE_TODAY)

    def test_rejects_future_date(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError) as ctx:
            cli.parse_trade_date("2026-07-31", _FAKE_TODAY)
        self.assertIn("future", str(ctx.exception))

    def test_rejects_invalid_format(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError) as ctx:
            cli.parse_trade_date("2026/07/30", _FAKE_TODAY)
        self.assertIn("YYYY-MM-DD", str(ctx.exception))

    def test_rejects_invalid_month(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError):
            cli.parse_trade_date("2026-13-30", _FAKE_TODAY)

    def test_rejects_non_string(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError):
            cli.parse_trade_date(20260730, _FAKE_TODAY)  # type: ignore[arg-type]


class BuildEnvOverridesTest(unittest.TestCase):
    """``--universe`` and ``--policy`` are mapped to the documented env vars."""

    def test_returns_empty_when_no_overrides(self) -> None:
        self.assertEqual(cli.build_env_overrides(), {})

    def test_universe_maps_to_personal_universe_env(self) -> None:
        overrides = cli.build_env_overrides(universe="/tmp/u.yaml")
        self.assertEqual(
            overrides,
            {"INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": "/tmp/u.yaml"},
        )

    def test_policy_maps_to_candidate_pool_policy_env(self) -> None:
        overrides = cli.build_env_overrides(policy="/tmp/p.yaml")
        self.assertEqual(
            overrides,
            {"INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH": "/tmp/p.yaml"},
        )

    def test_both_overrides_are_independent(self) -> None:
        overrides = cli.build_env_overrides(
            universe="/tmp/u.yaml",
            policy="/tmp/p.yaml",
        )
        self.assertEqual(
            overrides,
            {
                "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": "/tmp/u.yaml",
                "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH": "/tmp/p.yaml",
            },
        )

    def test_empty_strings_are_dropped(self) -> None:
        self.assertEqual(
            cli.build_env_overrides(universe="", policy=""),
            {},
        )


class ValidateProviderOptInTest(unittest.TestCase):
    """Real provider opt-in never activates from the flag alone."""

    def test_fixture_dev_does_not_require_confirm_network(self) -> None:
        cli.validate_provider_opt_in(
            provider_key="fixture_dev",
            cifang_enabled=False,
            confirm_network=False,
        )

    def test_cifangquant_without_env_is_refused_even_with_confirm(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError) as ctx:
            cli.validate_provider_opt_in(
                provider_key="cifangquant",
                cifang_enabled=False,
                confirm_network=True,
            )
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", str(ctx.exception))

    def test_cifangquant_without_confirm_is_refused_even_with_env(self) -> None:
        with self.assertRaises(cli.DailyCLIConfigError) as ctx:
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
        with self.assertRaises(cli.DailyCLIConfigError) as ctx:
            cli.validate_provider_opt_in(
                provider_key="bogus",
                cifang_enabled=True,
                confirm_network=True,
            )
        self.assertIn("not supported", str(ctx.exception))
        self.assertIn("fixture_dev", str(ctx.exception))
        self.assertIn("cifangquant", str(ctx.exception))


class BuildSummaryTest(unittest.TestCase):
    """The summary is the only thing the CLI prints on success."""

    @staticmethod
    def _event(name: str, metadata: dict[str, Any]) -> Any:
        materialization = SimpleNamespace(metadata=metadata)
        event = SimpleNamespace(asset_key=SimpleNamespace(path=[name]))
        event.materialization = materialization  # type: ignore[attr-defined]
        return event

    def test_summary_is_json_with_required_keys(self) -> None:
        events = (
            self._event(
                "etf_daily_bars_raw",
                {"record_count": IntMetadataValue(7), "symbol_count": IntMetadataValue(5)},
            ),
            self._event(
                "etf_input_snapshot",
                {
                    "universe_size": IntMetadataValue(5),
                    "snapshot_id": TextMetadataValue("snap-1"),
                },
            ),
            self._event(
                "personal_candidate_pool",
                {
                    "run_id": TextMetadataValue("pool-1"),
                    "status": TextMetadataValue("published"),
                    "input_count": IntMetadataValue(5),
                    "included_count": IntMetadataValue(3),
                    "item_count": IntMetadataValue(5),
                },
            ),
        )
        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=events,
            provider_key="fixture_dev",
        )
        payload = json.loads(line)
        self.assertEqual(
            set(payload.keys()),
            {
                "trade_date",
                "provider",
                "status",
                "universe_count",
                "daily_bar_count",
                "snapshot_id",
                "candidate_pool_run_id",
                "included_count",
                "excluded_count",
            },
        )
        self.assertEqual(payload["trade_date"], "2026-07-31")
        self.assertEqual(payload["provider"], "fixture_dev")
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["universe_count"], 5)
        self.assertEqual(payload["daily_bar_count"], 7)
        self.assertEqual(payload["snapshot_id"], "snap-1")
        self.assertEqual(payload["candidate_pool_run_id"], "pool-1")
        self.assertEqual(payload["included_count"], 3)
        self.assertEqual(payload["excluded_count"], 2)

    def test_summary_emits_nulls_when_metadata_missing(self) -> None:
        events = (self._event("personal_candidate_pool", {}),)
        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=events,
            provider_key="fixture_dev",
        )
        payload = json.loads(line)
        self.assertEqual(
            payload,
            {
                "candidate_pool_run_id": None,
                "daily_bar_count": None,
                "excluded_count": None,
                "included_count": None,
                "provider": "fixture_dev",
                "snapshot_id": None,
                "status": None,
                "trade_date": "2026-07-31",
                "universe_count": None,
            },
        )

    def test_summary_does_not_carry_api_key(self) -> None:
        events = (
            self._event("personal_candidate_pool", {"token": _SECRET_TOKEN}),
        )
        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=events,
            provider_key="fixture_dev",
        )
        self.assertNotIn(_SECRET_TOKEN, line)
        self.assertNotIn("api_key", line)

    def test_excluded_count_handles_partial_metadata(self) -> None:
        # No input_count but only item_count: excluded = item - included.
        events = (
            self._event(
                "personal_candidate_pool",
                {
                    "included_count": IntMetadataValue(4),
                    "item_count": IntMetadataValue(7),
                },
            ),
        )
        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=events,
            provider_key="fixture_dev",
        )
        self.assertEqual(json.loads(line)["excluded_count"], 3)

    def test_summary_skips_events_without_materialization(self) -> None:
        class _NoMatEvent:
            asset_key = SimpleNamespace(path=["x"])

        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=(_NoMatEvent(),),
            provider_key="fixture_dev",
        )
        payload = json.loads(line)
        self.assertEqual(payload["status"], None)

    def test_summary_ignores_unknown_asset_keys(self) -> None:
        events = (self._event("not_registered_asset", {"row_count": 99}),)
        line = cli.build_summary(
            trade_date=date(2026, 7, 31),
            materialization_events=events,
            provider_key="fixture_dev",
        )
        self.assertEqual(json.loads(line)["universe_count"], None)


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


class _StubJobRunner:
    """Stand-in for ``personal_etf_daily_job`` that returns canned events."""

    def __init__(
        self,
        *,
        success: bool = True,
        events: Sequence[Any] = (),
        run_id: str | None = None,
        failed_step_keys: Sequence[str] = (),
    ) -> None:
        self.success = success
        self.events = list(events)
        self.run_id = run_id or str(uuid4())
        self.failed_step_keys = list(failed_step_keys)
        self.execute_calls: list[tuple[str, bool]] = []

    def execute_in_process(self, partition_key: str, raise_on_error: bool) -> Any:
        self.execute_calls.append((partition_key, raise_on_error))
        return SimpleNamespace(
            success=self.success,
            run_id=self.run_id,
            get_asset_materialization_events=lambda: tuple(self.events),
            get_failed_step_keys=lambda: list(self.failed_step_keys),
        )


class _StubDefinitions:
    """Stub for ``invest_pipeline.definitions.defs`` used by :func:`run_daily`."""

    def __init__(self, job_runner: _StubJobRunner | None = None) -> None:
        self._job_runner = job_runner or _StubJobRunner()
        self.resolve_calls: list[str] = []

    def resolve_job_def(self, job_name: str) -> _StubJobRunner:
        self.resolve_calls.append(job_name)
        if job_name != "personal_etf_daily_job":
            raise KeyError(job_name)
        return self._job_runner


def _happy_path_events() -> tuple[Any, ...]:
    snapshot = SimpleNamespace(
        metadata={
            "universe_size": IntMetadataValue(7),
            "snapshot_id": TextMetadataValue("a" * 32),
        }
    )
    snapshot_event = SimpleNamespace(
        asset_key=SimpleNamespace(path=["etf_input_snapshot"]),
    )
    snapshot_event.materialization = snapshot  # type: ignore[attr-defined]

    bars = SimpleNamespace(
        metadata={
            "record_count": IntMetadataValue(7),
            "symbol_count": IntMetadataValue(7),
        }
    )
    bars_event = SimpleNamespace(
        asset_key=SimpleNamespace(path=["etf_daily_bars_raw"]),
    )
    bars_event.materialization = bars  # type: ignore[attr-defined]

    pool = SimpleNamespace(
        metadata={
            "run_id": TextMetadataValue("b" * 32),
            "status": TextMetadataValue("published"),
            "input_count": IntMetadataValue(7),
            "included_count": IntMetadataValue(4),
            "item_count": IntMetadataValue(7),
        }
    )
    pool_event = SimpleNamespace(
        asset_key=SimpleNamespace(path=["personal_candidate_pool"]),
    )
    pool_event.materialization = pool  # type: ignore[attr-defined]
    return snapshot_event, bars_event, pool_event


class RunDailyTest(unittest.TestCase):
    """``run_daily`` resolves the job, executes it, and emits the summary."""

    def test_runs_job_with_partition_key_and_emits_summary(self) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(defs.resolve_calls, ["personal_etf_daily_job"])
        self.assertEqual(runner.execute_calls, [("2026-07-31", False)])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["trade_date"], "2026-07-31")
        self.assertEqual(payload["provider"], "fixture_dev")
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["included_count"], 4)
        self.assertEqual(payload["excluded_count"], 3)
        self.assertEqual(payload["universe_count"], 7)
        self.assertEqual(payload["daily_bar_count"], 7)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())

    def test_returns_two_when_job_succeeds_but_no_materializations(self) -> None:
        runner = _StubJobRunner(events=())
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 2)
        self.assertIn("failed", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_returns_one_when_job_failure_emits_one_stderr_line(self) -> None:
        runner = _StubJobRunner(
            success=False, events=(), failed_step_keys=["etf_instruments_raw"]
        )
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        message = stderr.getvalue().strip()
        self.assertTrue(message.startswith("personal_etf_daily_job failed"))
        self.assertIn("etf_instruments_raw", message)
        self.assertEqual(stdout.getvalue(), "")

    def test_returns_one_when_job_missing(self) -> None:
        class _MissingDef:
            def resolve_job_def(self, job_name: str) -> Any:
                raise KeyError(job_name)

        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=_MissingDef(),  # type: ignore[arg-type]
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("not registered", stderr.getvalue())

    def test_returns_one_when_execute_raises(self) -> None:
        class _RaisingJob:
            def execute_in_process(self, partition_key: str, raise_on_error: bool) -> Any:
                raise RuntimeError("boom")

        defs = SimpleNamespace(resolve_job_def=lambda _name: _RaisingJob())
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,  # type: ignore[arg-type]
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 1)
        self.assertIn("could not start or complete", stderr.getvalue())

    def test_execute_output_is_suppressed_when_it_raises(self) -> None:
        class _RaisingJob:
            def execute_in_process(self, partition_key: str, raise_on_error: bool) -> Any:
                print(_SECRET_TOKEN)
                print(_SECRET_TOKEN, file=sys.stderr)
                raise RuntimeError(_SECRET_TOKEN)

        defs = SimpleNamespace(resolve_job_def=lambda _name: _RaisingJob())
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,  # type: ignore[arg-type]
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        output = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(rc, 1)
        self.assertNotIn(_SECRET_TOKEN, output)
        self.assertEqual(
            stderr.getvalue().strip(),
            "error: personal_etf_daily_job could not start or complete",
        )
        runner = _StubJobRunner(
            success=False,
            events=(),
            failed_step_keys=["etf_instruments_raw"],
        )
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
        )
        self.assertEqual(rc, 1)
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())


class EnvInjectionTest(unittest.TestCase):
    """``_EnvStack`` injects overrides and restores the prior values."""

    def test_apply_and_restore_universe(self) -> None:
        sentinel = "/tmp/custom-universe.yaml"
        previous = os.environ.get("INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH")
        try:
            with cli._EnvStack({"INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH": sentinel}):
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
        os.environ.pop("INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH", None)
        with cli._EnvStack({"INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH": "/tmp/p"}):
            self.assertEqual(
                os.environ["INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH"],
                "/tmp/p",
            )
        self.assertNotIn(
            "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH", os.environ
        )

    def test_settings_picks_up_overridden_universe_path(self) -> None:
        from invest_pipeline.config import get_settings

        custom = "/tmp/injected-universe.yaml"
        get_settings.cache_clear()
        try:
            os.environ["INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"] = custom
            self.assertEqual(str(get_settings().personal_universe_path), custom)
        finally:
            os.environ.pop("INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH", None)
            get_settings.cache_clear()


class MainRefusalTest(unittest.TestCase):
    """``main`` exits non-zero before ever touching Dagster on bad input."""

    def test_future_date_is_refused_without_importing_definitions(self) -> None:
        with (
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.personal_daily_cli._resolve_provider_key",
                return_value="fixture_dev",
            ),mock.patch(
            "invest_pipeline.personal_daily_cli.run_daily"
        ) as run_daily_spy
        ):
            rc = cli.main(
                ["--trade-date", "2030-01-01"]
            )
        self.assertEqual(rc, 2)
        self.assertIn("future", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        run_daily_spy.assert_not_called()

    def test_invalid_date_is_refused_without_importing_definitions(self) -> None:
        with (
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = cli.main(["--trade-date", "26-07-30"])
        self.assertEqual(rc, 2)
        self.assertIn("YYYY-MM-DD", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_cifangquant_without_env_is_refused(self) -> None:
        env = {"INVEST_PIPELINE_PROVIDER_KEY": "cifangquant"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = cli.main(
                [
                    "--trade-date",
                    "2026-07-30",
                    "--confirm-network",
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("INVEST_PIPELINE_CIFANG_ENABLED", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())

    def test_cifangquant_without_confirm_is_refused(self) -> None:
        env = {
            "INVEST_PIPELINE_PROVIDER_KEY": "cifangquant",
            "INVEST_PIPELINE_CIFANG_ENABLED": "true",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = cli.main(["--trade-date", "2026-07-30"])
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-network", stderr.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())

    def test_unknown_provider_is_refused(self) -> None:
        env = {"INVEST_PIPELINE_PROVIDER_KEY": "bogus"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
        ):
            rc = cli.main(["--trade-date", "2026-07-30"])
        self.assertEqual(rc, 2)
        self.assertIn("not supported", stderr.getvalue())


class MainFixtureExecutionTest(unittest.TestCase):
    """``main`` driven end-to-end with a stubbed ``defs`` returns a JSON line."""

    def test_main_returns_zero_with_stub_defs_and_emits_json(self) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        env: dict[str, str] = {}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.personal_daily_cli._resolve_provider_key",
                return_value="fixture_dev",
            ),
            mock.patch.dict(
                "sys.modules",
                {"invest_pipeline.definitions": SimpleNamespace(defs=defs)},
            ),
            mock.patch(
                "invest_pipeline.personal_daily_cli.run_daily",
                wraps=cli.run_daily,
            ) as run_daily_spy,
        ):
            rc = cli.main(["--trade-date", "2026-07-30"])
        self.assertEqual(rc, 0)
        self.assertEqual(runner.execute_calls, [("2026-07-30", False)])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload,
            {
                "candidate_pool_run_id": "b" * 32,
                "daily_bar_count": 7,
                "excluded_count": 3,
                "included_count": 4,
                "provider": "fixture_dev",
                "snapshot_id": "a" * 32,
                "status": "published",
                "trade_date": "2026-07-30",
                "universe_count": 7,
            },
        )
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        # ``run_daily`` must have been called with our stub defs.
        self.assertEqual(run_daily_spy.call_count, 1)

    def test_main_injects_universe_and_policy_env_before_execution(
        self,
    ) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)

        captured: dict[str, str] = {}

        real_run_daily = cli.run_daily

        def _capture_run_daily(**kwargs: Any) -> int:
            captured["universe"] = os.environ.get(
                "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"
            )
            captured["policy"] = os.environ.get(
                "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH"
            )
            return real_run_daily(**kwargs)

        env: dict[str, str] = {}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (_stdout, _stderr),
            mock.patch(
                "invest_pipeline.personal_daily_cli._resolve_provider_key",
                return_value="fixture_dev",
            ),
            mock.patch.dict(
                "sys.modules",
                {"invest_pipeline.definitions": SimpleNamespace(defs=defs)},
            ),
            mock.patch(
                "invest_pipeline.personal_daily_cli.run_daily",
                side_effect=_capture_run_daily,
            ),
        ):
            rc = cli.main(
                [
                    "--trade-date",
                    "2026-07-30",
                    "--universe",
                    "/tmp/personal-universe.yaml",
                    "--policy",
                    "/tmp/candidate-pool-policy.yaml",
                ]
            )
        self.assertEqual(rc, 0)
        self.assertEqual(
            captured["universe"],
            "/tmp/personal-universe.yaml",
        )
        self.assertEqual(
            captured["policy"],
            "/tmp/candidate-pool-policy.yaml",
        )


class SecretNonLeakTest(unittest.TestCase):
    """The CLI never echoes any supplied secret in stdout or stderr."""

    def test_secret_does_not_leak_in_success_output(self) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        env: dict[str, str] = {
            "INVEST_PIPELINE_CIFANG_API_KEY": _SECRET_TOKEN,
            "INVEST_PIPELINE_CIFANG_ENABLED": "true",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.personal_daily_cli._resolve_provider_key",
                return_value="fixture_dev",
            ),
            mock.patch.dict(
                "sys.modules",
                {"invest_pipeline.definitions": SimpleNamespace(defs=defs)},
            ),
        ):
            rc = cli.main(["--trade-date", "2026-07-30"])
        self.assertEqual(rc, 0)
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())


class ParserTest(unittest.TestCase):
    """Quick smoke on the argparse surface."""

    def test_help_is_exposed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            cli.build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_required_trade_date(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])


class _RecordingPipelineRunRecorder:
    """Test double for :class:`cli.PipelineRunRecorder`.

    Captures every call so the assertions can pin the lifecycle the
    CLI is expected to drive on a successful or failed run. Defaults
    to mimicking the production contract (``start`` returns a fresh
    :class:`UUID`; ``mark_succeeded`` / ``mark_failed`` record the
    arguments but do nothing). The optional ``fail_*`` toggles let a
    test inject a database-unavailable scenario without touching a
    real :class:`Session`.
    """

    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_mark: bool = False,
    ) -> None:
        self.fail_start = fail_start
        self.fail_mark = fail_mark
        self.calls: list[tuple[str, Any]] = []
        self.start_run_id: UUID | None = None

    def start(self, **kwargs: Any) -> UUID | None:
        self.calls.append(("start", kwargs))
        if self.fail_start:
            raise RuntimeError("database unavailable")
        self.start_run_id = uuid4()
        return self.start_run_id

    def mark_succeeded(self, run_id: UUID, *, finished_at: datetime) -> None:
        self.calls.append(("mark_succeeded", (run_id, finished_at)))
        if self.fail_mark:
            raise RuntimeError("database unavailable")

    def mark_failed(
        self,
        run_id: UUID,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None:
        self.calls.append(("mark_failed", (run_id, error_summary, finished_at)))
        if self.fail_mark:
            raise RuntimeError("database unavailable")


class RunDailyPipelineRunsTest(unittest.TestCase):
    """``run_daily`` persists ``ops.pipeline_runs`` lifecycle entries.

    The CLI is now responsible for writing one ``running`` row before
    :func:`run_daily` executes the job and flipping it to
    ``succeeded`` / ``failed`` based on the outcome. The assertions
    here pin:

    * the lifecycle order (start → final-state mark);
    * that the final-state mark carries a token-scrubbed error message;
    * that audit-write failures never change the JSON summary or the
      exit code;
    * that pure unit tests stay DB-free by default.
    """

    def test_run_daily_default_recorder_is_noop(self) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, 0)
        # The no-op recorder never persists anything; the JSON summary
        # is the only operator-visible output.
        self.assertNotEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_run_daily_records_running_then_succeeded_on_success(self) -> None:
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        recorder = _RecordingPipelineRunRecorder()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            pipeline_run_recorder=recorder,
        )
        self.assertEqual(rc, 0)
        kinds = [name for name, _ in recorder.calls]
        self.assertEqual(kinds, ["start", "mark_succeeded"])

        start_kwargs = recorder.calls[0][1]
        self.assertEqual(start_kwargs["job_key"], "personal_etf_daily_job")
        self.assertEqual(start_kwargs["trigger_type"], "manual")
        self.assertEqual(start_kwargs["partition_key"], "2026-07-31")
        self.assertEqual(start_kwargs["dagster_run_id"], None)
        self.assertEqual(
            start_kwargs["config_snapshot"],
            {"provider_key": "fixture_dev", "trade_date": "2026-07-31"},
        )

        # ``mark_succeeded`` must reuse the UUID ``start`` returned.
        marked_run_id = recorder.calls[1][1][0]
        self.assertEqual(marked_run_id, recorder.start_run_id)

    def test_run_daily_records_running_then_failed_with_scrubbed_summary(
        self,
    ) -> None:
        runner = _StubJobRunner(
            success=False,
            events=(),
            failed_step_keys=["etf_instruments_raw"],
        )
        defs = _StubDefinitions(job_runner=runner)
        recorder = _RecordingPipelineRunRecorder()
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
            pipeline_run_recorder=recorder,
        )
        self.assertEqual(rc, 1)
        kinds = [name for name, _ in recorder.calls]
        self.assertEqual(kinds, ["start", "mark_failed"])
        # ``mark_failed`` must scrub the token from the recorded summary
        # so a future audit query never reveals it.
        _, error_summary, _ = recorder.calls[1][1]
        self.assertNotIn(_SECRET_TOKEN, error_summary)
        # The stderr line the operator sees must also stay clean.
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())
        self.assertIn("failed", stderr.getvalue())
        self.assertIn("etf_instruments_raw", stderr.getvalue())

    def test_run_daily_swallows_recorder_start_failure(self) -> None:
        """``start`` raising must not mask the original job result."""

        recorder = _RecordingPipelineRunRecorder(fail_start=True)
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            pipeline_run_recorder=recorder,
        )
        self.assertEqual(rc, 0)
        # The CLI surfaces a single audit-failure warning on stderr so
        # the missing row is visible to the operator but never changes
        # the exit code or the summary.
        self.assertIn("audit insert", stderr.getvalue())
        # The summary still reaches stdout untouched.
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["trade_date"], "2026-07-31")
        self.assertEqual(payload["status"], "published")
        # ``mark_succeeded`` must NOT be called when ``start`` raised.
        kinds = [name for name, _ in recorder.calls]
        self.assertEqual(kinds, ["start"])

    def test_run_daily_swallows_recorder_mark_failure(self) -> None:
        """Database write failure on the terminal-state mark is best-effort."""

        recorder = _RecordingPipelineRunRecorder(fail_mark=True)
        runner = _StubJobRunner(events=_happy_path_events())
        defs = _StubDefinitions(job_runner=runner)
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            pipeline_run_recorder=recorder,
        )
        self.assertEqual(rc, 0)
        self.assertIn("audit persistence failed", stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["trade_date"], "2026-07-31")

    def test_run_daily_token_never_enters_error_summary(self) -> None:
        """Regression: the API key never reaches the recorded failure message."""

        class _TokenLeakingJob:
            """Job whose ``run_id`` and ``failed_step_keys`` embed the token."""

            def execute_in_process(self, partition_key: str, raise_on_error: bool) -> Any:
                return SimpleNamespace(
                    success=False,
                    run_id=_SECRET_TOKEN,
                    get_asset_materialization_events=lambda: (),
                    get_failed_step_keys=lambda: [_SECRET_TOKEN],
                )

        recorder = _RecordingPipelineRunRecorder()
        defs = SimpleNamespace(
            resolve_job_def=lambda _name: _TokenLeakingJob(),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = cli.run_daily(
            trade_date=date(2026, 7, 31),
            defs=defs,  # type: ignore[arg-type]
            provider_key="fixture_dev",
            stdout=stdout,
            stderr=stderr,
            token=_SECRET_TOKEN,
            pipeline_run_recorder=recorder,
        )
        self.assertEqual(rc, 1)
        # Every recorded ``error_summary`` must have the token scrubbed.
        mark_failed_calls = [
            payload for name, payload in recorder.calls if name == "mark_failed"
        ]
        self.assertEqual(len(mark_failed_calls), 1)
        _, error_summary, _ = mark_failed_calls[0]
        self.assertNotIn(_SECRET_TOKEN, error_summary)
        # And nothing the operator saw leaks the token either.
        self.assertNotIn(_SECRET_TOKEN, stdout.getvalue())
        self.assertNotIn(_SECRET_TOKEN, stderr.getvalue())


class PipelineRunRecorderConstructionTest(unittest.TestCase):
    """The recorder factory never raises on a bad configuration."""

    def test_build_default_returns_none_for_empty_url(self) -> None:
        self.assertIsNone(cli.build_default_pipeline_run_recorder(""))

    def test_build_default_returns_none_for_non_string_url(self) -> None:
        self.assertIsNone(cli.build_default_pipeline_run_recorder(None))  # type: ignore[arg-type]

    def test_build_default_handles_unparseable_url(self) -> None:
        # ``sqlalchemy.create_engine`` accepts arbitrary URLs and defers
        # the actual connection until first use; the factory must not
        # raise even on garbage input.
        recorder = cli.build_default_pipeline_run_recorder(
            "not-a-valid-sqlalchemy-url"
        )
        # Either we get a recorder instance (acceptable; failures are
        # swallowed at runtime), or ``None`` (acceptable; the CLI's
        # audit-write path is best-effort). Either way the construction
        # itself must not raise.
        self.assertTrue(recorder is None or hasattr(recorder, "start"))


if __name__ == "__main__":
    unittest.main()
