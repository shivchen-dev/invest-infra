from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock
from uuid import UUID

import pytest
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.real_exposure_cli import (
    RealExposureCLIConfigError,
    build_parser,
    main,
    run,
    validate_opt_in,
)
from invest_pipeline.real_exposure_service import RealExposurePersistResult

_REQUIRED = [
    "--etf-symbol", "510300", "--etf-exchange", "SSE",
    "--index-code", "000300", "--mapping-effective-from", "2026-01-01",
    "--observed-at", "2026-08-01T00:00:00+00:00",
]
_OPT_IN_ENV = {"INVEST_PIPELINE_AKSHARE_ENABLED": "true"}
_AKSHARE_ENABLED_ENV = "INVEST_PIPELINE_AKSHARE_ENABLED"


def test_required_arguments_and_no_inferred_effective_date() -> None:
    args = build_parser().parse_args(_REQUIRED + ["--confirm-network"])
    assert args.mapping_effective_from == date(2026, 1, 1)
    assert args.observed_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert args.mapping_effective_to is None
    assert args.confirm_network is True


def test_confirm_network_defaults_to_false() -> None:
    args = build_parser().parse_args(_REQUIRED)
    assert args.confirm_network is False


def test_missing_required_argument_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(_REQUIRED[:-2] + ["--confirm-network"])
    assert exc_info.value.code == 2


def test_run_emits_deterministic_json_and_passes_options() -> None:
    result = RealExposurePersistResult(
        etf_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        index_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        profile_id=UUID("11111111-1111-4111-8111-111111111111"),
        profile_content_hash="p",
        constituent_snapshot_id=UUID("22222222-2222-4222-8222-222222222222"),
        constituent_content_hash="c",
        mapping_id=UUID("33333333-3333-4333-8333-333333333333"), mapping_content_hash="m",
        holding_snapshot_id=UUID("44444444-4444-4444-8444-444444444444"),
        holding_content_hash="h",
        constituents_raw_payload_hash="a", holdings_raw_payload_hash="b",
    )
    client = object()
    captured = {}

    def factory():
        return object()

    def service(**kwargs):
        captured.update(kwargs)
        return result

    import invest_pipeline.real_exposure_cli as module
    original = module.collect_and_persist_real_exposure
    module.collect_and_persist_real_exposure = service
    try:
        args = build_parser().parse_args(
            _REQUIRED + ["--holding-year", "2025", "--confidence", "0.5"]
        )
        output = StringIO()
        assert run(args=args, client=client, uow_factory=factory, stdout=output) == 0
        assert json.loads(output.getvalue())["profile_id"] == str(result.profile_id)
        assert captured["holding_year"] == "2025"
        assert captured["confidence"] == Decimal("0.5")
    finally:
        module.collect_and_persist_real_exposure = original


class ValidateOptInTest(unittest.TestCase):
    """The double-gate must catch every missing lever before construction."""

    def test_rejects_when_akshare_disabled(self) -> None:
        settings = AkshareSettings()
        with self.assertRaises(RealExposureCLIConfigError) as ctx:
            validate_opt_in(settings, confirm_network=True)
        self.assertIn(_AKSHARE_ENABLED_ENV, str(ctx.exception))

    def test_rejects_without_confirm_network(self) -> None:
        settings = AkshareSettings()
        object.__setattr__(settings, "enabled", True)
        with self.assertRaises(RealExposureCLIConfigError) as ctx:
            validate_opt_in(settings, confirm_network=False)
        self.assertIn("--confirm-network", str(ctx.exception))

    def test_rejects_disabled_first_when_both_missing(self) -> None:
        settings = AkshareSettings()
        with self.assertRaises(RealExposureCLIConfigError) as ctx:
            validate_opt_in(settings, confirm_network=False)
        self.assertIn(_AKSHARE_ENABLED_ENV, str(ctx.exception))

    def test_passes_when_both_enabled(self) -> None:
        settings = AkshareSettings()
        object.__setattr__(settings, "enabled", True)
        # Should not raise.
        validate_opt_in(settings, confirm_network=True)


class _CaptureStdStreams:
    """Redirect ``sys.stdout`` and ``sys.stderr`` for the duration of a block."""

    def __enter__(self) -> tuple[StringIO, StringIO]:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._stdout_patch = mock.patch("sys.stdout", self._stdout)
        self._stderr_patch = mock.patch("sys.stderr", self._stderr)
        self._stdout_patch.__enter__()
        self._stderr_patch.__enter__()
        return self._stdout, self._stderr

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stdout_patch.__exit__(exc_type, exc, tb)
        self._stderr_patch.__exit__(exc_type, exc, tb)


class MainRefusalTest(unittest.TestCase):
    """``main`` must exit non-zero before reaching the network and before
    constructing engine / client whenever a gate is missing."""

    def _assert_no_construction(
        self,
        *,
        stdout: StringIO,
        stderr: StringIO,
        engine_spy: mock.MagicMock,
        sessionmaker_spy: mock.MagicMock,
        client_spy: mock.MagicMock,
    ) -> None:
        self.assertEqual(engine_spy.call_count, 0)
        self.assertEqual(sessionmaker_spy.call_count, 0)
        self.assertEqual(client_spy.call_count, 0)
        self.assertIn("refused:", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_main_returns_two_without_confirm_network(self) -> None:
        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.real_exposure_cli.create_engine"
            ) as engine_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.sessionmaker"
            ) as sessionmaker_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.AkshareClient"
            ) as client_spy,
        ):
            rc = main(_REQUIRED)
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-network", stderr.getvalue())
        self._assert_no_construction(
            stdout=stdout,
            stderr=stderr,
            engine_spy=engine_spy,
            sessionmaker_spy=sessionmaker_spy,
            client_spy=client_spy,
        )

    def test_main_returns_two_without_enablement(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("INVEST_PIPELINE_AKSHARE_")
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.real_exposure_cli.create_engine"
            ) as engine_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.sessionmaker"
            ) as sessionmaker_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.AkshareClient"
            ) as client_spy,
        ):
            rc = main(_REQUIRED + ["--confirm-network"])
        self.assertEqual(rc, 2)
        self.assertIn(_AKSHARE_ENABLED_ENV, stderr.getvalue())
        self._assert_no_construction(
            stdout=stdout,
            stderr=stderr,
            engine_spy=engine_spy,
            sessionmaker_spy=sessionmaker_spy,
            client_spy=client_spy,
        )

    def test_main_returns_two_without_either_gate(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("INVEST_PIPELINE_AKSHARE_")
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch(
                "invest_pipeline.real_exposure_cli.create_engine"
            ) as engine_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.sessionmaker"
            ) as sessionmaker_spy,
            mock.patch(
                "invest_pipeline.real_exposure_cli.AkshareClient"
            ) as client_spy,
        ):
            rc = main(_REQUIRED)
        self.assertEqual(rc, 2)
        self.assertIn("refused:", stderr.getvalue())
        # Disabled wins the message because it is checked first.
        self.assertIn(_AKSHARE_ENABLED_ENV, stderr.getvalue())
        self._assert_no_construction(
            stdout=stdout,
            stderr=stderr,
            engine_spy=engine_spy,
            sessionmaker_spy=sessionmaker_spy,
            client_spy=client_spy,
        )


class MainHappyPathTest(unittest.TestCase):
    """``main`` with both gates and stubbed collaborators returns the redacted JSON."""

    def test_main_returns_zero_and_constructs_after_both_gates(self) -> None:
        fake_settings = SimpleNamespace(database_url="postgresql+psycopg://stub")
        fake_engine = mock.MagicMock(name="engine")
        fake_session_factory = mock.MagicMock(name="session_factory")
        fake_client = mock.MagicMock(name="akshare_client")

        result = RealExposurePersistResult(
            etf_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            index_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            profile_id=UUID("11111111-1111-4111-8111-111111111111"),
            profile_content_hash="p",
            constituent_snapshot_id=UUID("22222222-2222-4222-8222-222222222222"),
            constituent_content_hash="c",
            mapping_id=UUID("33333333-3333-4333-8333-333333333333"),
            mapping_content_hash="m",
            holding_snapshot_id=UUID("44444444-4444-4444-8444-444444444444"),
            holding_content_hash="h",
            constituents_raw_payload_hash="a",
            holdings_raw_payload_hash="b",
        )

        import invest_pipeline.real_exposure_cli as module

        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch.object(
                module, "get_settings", return_value=fake_settings
            ) as settings_spy,
            mock.patch.object(
                module,
                "create_engine",
                return_value=fake_engine,
            ) as engine_spy,
            mock.patch.object(
                module,
                "sessionmaker",
                return_value=fake_session_factory,
            ) as sessionmaker_spy,
            mock.patch.object(
                module,
                "AkshareClient",
                return_value=fake_client,
            ) as client_spy,
            mock.patch.object(
                module,
                "collect_and_persist_real_exposure",
                return_value=result,
            ) as service_spy,
        ):
            rc = main(_REQUIRED + ["--confirm-network"])

        self.assertEqual(rc, 0)
        # Both gates satisfied, so settings + engine + client are built.
        self.assertEqual(settings_spy.call_count, 1)
        self.assertEqual(engine_spy.call_count, 1)
        self.assertEqual(sessionmaker_spy.call_count, 1)
        self.assertEqual(client_spy.call_count, 1)
        # The real service is invoked with the constructed client / uow.
        self.assertEqual(service_spy.call_count, 1)
        kwargs = service_spy.call_args.kwargs
        self.assertIs(kwargs["client"], fake_client)
        # engine is disposed after the run.
        self.assertEqual(fake_engine.dispose.call_count, 1)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["profile_id"], str(result.profile_id))
        self.assertEqual(payload["mapping_id"], str(result.mapping_id))
        self.assertEqual(stderr.getvalue(), "")


class MainOperationalErrorTest(unittest.TestCase):
    """``main`` must catch operational exceptions from session_factory /
    client / run, emit exactly one sanitized stderr line with no
    exception type, message, traceback, or secrets, return ``1``, and
    always dispose the engine."""

    _SANITIZED_LINE = "error: operation failed\n"

    def _assert_sanitized(
        self,
        *,
        stdout: StringIO,
        stderr: StringIO,
        engine: mock.MagicMock,
        rc: int,
    ) -> None:
        self.assertEqual(rc, 1)
        self.assertEqual(stdout.getvalue(), "")
        err = stderr.getvalue()
        self.assertEqual(err, self._SANITIZED_LINE)
        self.assertEqual(err.count("\n"), 1)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("RuntimeError", err)
        self.assertNotIn("super_secret", err)
        self.assertNotIn("postgresql", err)
        self.assertEqual(engine.dispose.call_count, 1)

    def test_run_failure_is_sanitized_and_engine_disposed(self) -> None:
        fake_settings = SimpleNamespace(database_url="postgresql+psycopg://stub")
        fake_engine = mock.MagicMock(name="engine")
        secret_message = (
            "db boom: postgresql://admin:super_secret_123@db.example.com/prod"
        )

        import invest_pipeline.real_exposure_cli as module

        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch.object(module, "get_settings", return_value=fake_settings),
            mock.patch.object(module, "create_engine", return_value=fake_engine),
            mock.patch.object(module, "sessionmaker", return_value=mock.MagicMock()),
            mock.patch.object(module, "AkshareClient", return_value=mock.MagicMock()),
            mock.patch.object(
                module,
                "collect_and_persist_real_exposure",
                side_effect=RuntimeError(secret_message),
            ),
        ):
            rc = main(_REQUIRED + ["--confirm-network"])

        self._assert_sanitized(
            stdout=stdout,
            stderr=stderr,
            engine=fake_engine,
            rc=rc,
        )

    def test_client_construction_failure_is_sanitized_and_engine_disposed(self) -> None:
        fake_settings = SimpleNamespace(database_url="postgresql+psycopg://stub")
        fake_engine = mock.MagicMock(name="engine")
        secret_message = "akshare init failed: token=super_secret_TOKEN"

        import invest_pipeline.real_exposure_cli as module

        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch.object(module, "get_settings", return_value=fake_settings),
            mock.patch.object(module, "create_engine", return_value=fake_engine),
            mock.patch.object(module, "sessionmaker", return_value=mock.MagicMock()),
            mock.patch.object(
                module,
                "AkshareClient",
                side_effect=RuntimeError(secret_message),
            ),
        ):
            rc = main(_REQUIRED + ["--confirm-network"])

        self._assert_sanitized(
            stdout=stdout,
            stderr=stderr,
            engine=fake_engine,
            rc=rc,
        )

    def test_sessionmaker_failure_is_sanitized_and_engine_disposed(self) -> None:
        fake_settings = SimpleNamespace(database_url="postgresql+psycopg://stub")
        fake_engine = mock.MagicMock(name="engine")
        secret_message = "sessionmaker init failed: password=super_secret_PWD"

        import invest_pipeline.real_exposure_cli as module

        with (
            mock.patch.dict(os.environ, _OPT_IN_ENV, clear=True),
            _CaptureStdStreams() as (stdout, stderr),
            mock.patch.object(module, "get_settings", return_value=fake_settings),
            mock.patch.object(module, "create_engine", return_value=fake_engine),
            mock.patch.object(
                module,
                "sessionmaker",
                side_effect=RuntimeError(secret_message),
            ),
        ):
            rc = main(_REQUIRED + ["--confirm-network"])

        self._assert_sanitized(
            stdout=stdout,
            stderr=stderr,
            engine=fake_engine,
            rc=rc,
        )


if __name__ == "__main__":
    unittest.main()
