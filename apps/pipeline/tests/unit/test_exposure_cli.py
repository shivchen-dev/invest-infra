"""Focused unit tests for the DC-3 exposure persistence CLI.

Covers:
* ``--etf-id`` parser / default fixture resolution.
* ETF rebinding in both ``etf_index_mapping`` and ``etf_holdings`` sections
  without mutating the adapter-owned payload.
* Service call wiring.
* Deterministic redacted success JSON output.
* Invalid UUID aborts before adapter / UoW are accessed.
* Adapter and service error translation to ``error: ...`` stderr.
* Engine disposal in production wiring.
"""

from __future__ import annotations

import io
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

from invest_pipeline import exposure_cli as cli
from invest_pipeline.adapters.errors import RealProviderRequiresExplicitEnablementError
from invest_pipeline.exposure_service import (
    EtfIdMismatchError,
    ExposureServiceError,
    IndexCodeMismatchError,
    InstrumentNotFoundError,
)

_FAKE_ETF_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_FAKE_INDEX_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _fake_result() -> Any:
    return SimpleNamespace(
        index_id=_FAKE_INDEX_ID,
        profile_id=uuid4(),
        profile_content_hash="phash",
        constituent_snapshot_id=uuid4(),
        constituent_content_hash="chash",
        mapping_id=uuid4(),
        mapping_content_hash="mhash",
        holding_snapshot_id=uuid4(),
        holding_content_hash="hhash",
    )


class RebindEtfIdTest(unittest.TestCase):
    """``_rebind_etf_id`` writes a deep copy; the original payload is untouched."""

    def test_both_sections_rebound(self) -> None:
        payload = {
            "etf_index_mapping": {"etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            "etf_holdings": {"etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        }
        rebound = cli._rebind_etf_id(payload, _FAKE_ETF_ID)
        self.assertEqual(rebound["etf_index_mapping"]["etf_id"], str(_FAKE_ETF_ID))
        self.assertEqual(rebound["etf_holdings"]["etf_id"], str(_FAKE_ETF_ID))

    def test_original_unchanged(self) -> None:
        payload = {
            "etf_index_mapping": {"etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            "etf_holdings": {"etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        }
        original = deepcopy(payload)
        cli._rebind_etf_id(payload, _FAKE_ETF_ID)
        self.assertEqual(payload, original)

    def test_deep_nested_unchanged(self) -> None:
        payload = {
            "etf_index_mapping": {
                "etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "nested": {"foo": "bar"},
            },
            "etf_holdings": {
                "etf_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "nested": ["list"],
            },
        }
        original = deepcopy(payload)
        cli._rebind_etf_id(payload, _FAKE_ETF_ID)
        self.assertEqual(payload, original)


class BuildSuccessLineTest(unittest.TestCase):
    def _result(self, **kwargs: Any) -> Any:
        defaults = dict(
            index_id=uuid4(),
            profile_id=uuid4(),
            profile_content_hash="ph",
            constituent_snapshot_id=uuid4(),
            constituent_content_hash="ch",
            mapping_id=uuid4(),
            mapping_content_hash="mh",
            holding_snapshot_id=uuid4(),
            holding_content_hash="hh",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_all_keys_present(self) -> None:
        result = self._result()
        line = cli._build_success_line(result)
        parsed = json.loads(line)
        expect = {
            "index_id",
            "profile_id",
            "profile_content_hash",
            "constituent_snapshot_id",
            "constituent_content_hash",
            "mapping_id",
            "mapping_content_hash",
            "holding_snapshot_id",
            "holding_content_hash",
        }
        self.assertEqual(set(parsed.keys()), expect)

    def test_deterministic(self) -> None:
        result = self._result(
            index_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            profile_id=UUID("11111111-1111-4111-8111-111111111111"),
            profile_content_hash="abc",
        )
        line1 = cli._build_success_line(result)
        line2 = cli._build_success_line(result)
        self.assertEqual(line1, line2)

    def test_no_raw_payload_leaks(self) -> None:
        result = self._result()
        line = cli._build_success_line(result)
        self.assertNotIn("payload", line)
        self.assertNotIn("database_url", line)


class TranslateErrorTest(unittest.TestCase):
    def test_real_provider_error(self) -> None:
        msg = cli._translate_error(RealProviderRequiresExplicitEnablementError("disabled"))
        self.assertTrue(msg.startswith("adapter error:"))

    def test_file_not_found(self) -> None:
        msg = cli._translate_error(FileNotFoundError("no/such/path.json"))
        self.assertTrue(msg.startswith("fixture not found:"))

    def test_instrument_not_found(self) -> None:
        msg = cli._translate_error(InstrumentNotFoundError("etf 000 not found"))
        self.assertTrue(msg.startswith("instrument error:"))

    def test_etf_id_mismatch(self) -> None:
        msg = cli._translate_error(EtfIdMismatchError("etf_id mismatch"))
        self.assertTrue(msg.startswith("payload validation error:"))

    def test_index_code_mismatch(self) -> None:
        msg = cli._translate_error(IndexCodeMismatchError("index_code mismatch"))
        self.assertTrue(msg.startswith("payload validation error:"))

    def test_exposure_service_error(self) -> None:
        msg = cli._translate_error(ExposureServiceError("generic"))
        self.assertTrue(msg.startswith("service error:"))

    def test_value_error(self) -> None:
        msg = cli._translate_error(ValueError("bad thing"))
        self.assertTrue(msg.startswith("malformed payload:"))

    def test_generic_exception(self) -> None:
        msg = cli._translate_error(RuntimeError("boom"))
        self.assertTrue(msg.startswith("storage error:"))
        self.assertEqual(msg, "storage error: operation failed")

    def test_generic_exception_does_not_leak_db_url(self) -> None:
        fake_db_url = "postgresql://admin:super_secret_123@db.example.com:5432/prod"
        msg = cli._translate_error(RuntimeError(fake_db_url))
        self.assertTrue(msg.startswith("storage error:"))
        self.assertEqual(msg, "storage error: operation failed")
        self.assertNotIn("postgresql", msg)
        self.assertNotIn("super_secret", msg)
        self.assertNotIn("db.example.com", msg)


class ParserTest(unittest.TestCase):
    def test_etf_id_required(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_invalid_uuid_exits(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--etf-id", "not-a-uuid"])

    def test_valid_uuid_parses(self) -> None:
        args = cli.build_parser().parse_args(["--etf-id", str(_FAKE_ETF_ID)])
        self.assertEqual(args.etf_id, _FAKE_ETF_ID)

    def test_optional_fixture_path(self) -> None:
        args = cli.build_parser().parse_args(["--etf-id", str(_FAKE_ETF_ID)])
        self.assertIsNone(args.fixture_path)

        args2 = cli.build_parser().parse_args(
            ["--etf-id", str(_FAKE_ETF_ID), "--fixture-path", "/tmp/foo.json"]
        )
        self.assertEqual(args2.fixture_path, "/tmp/foo.json")


class RunTest(unittest.TestCase):
    """``run`` wires adapter → rebind → service → output."""

    def test_calls_adapter_with_fixture_path(self) -> None:
        fake_payload = {
            "provider_key": "akshare",
            "dataset_key": "exposure_bundle",
            "observed_at": "2026-07-31T12:00:00+00:00",
            "index_profile": {
                "index_code": "000300",
                "index_name": "CSI 300",
                "category": "Broad Market",
            },
            "index_constituents": {
                "index_code": "000300",
                "as_of_date": "2026-07-31",
                "constituents": [],
            },
            "etf_index_mapping": {"etf_id": "x", "index_id": "y", "effective_from": "2024-01-01"},
            "etf_holdings": {"etf_id": "x", "as_of_date": "2026-07-31", "holdings": []},
        }
        adapter = SimpleNamespace(fetch_standardized_payload=mock.Mock(return_value=fake_payload))
        result = _fake_result()
        with mock.patch.object(cli, "persist_exposure", return_value=result) as persist_spy:
            stdout = io.StringIO()
            rc = cli.run(
                etf_id=_FAKE_ETF_ID,
                fixture_path="/custom/path.json",
                adapter=adapter,  # type: ignore[arg-type]
                uow_factory=mock.Mock(),
                stdout=stdout,
            )
        adapter.fetch_standardized_payload.assert_called_once_with(fixture_path="/custom/path.json")
        persist_spy.assert_called_once()
        self.assertEqual(rc, 0)

    def test_calls_persist_exposure_with_rebound_payload(self) -> None:
        fake_payload = {
            "provider_key": "akshare",
            "dataset_key": "exposure_bundle",
            "observed_at": "2026-07-31T12:00:00+00:00",
            "index_profile": {
                "index_code": "000300",
                "index_name": "CSI 300",
                "category": "Broad Market",
            },
            "index_constituents": {
                "index_code": "000300",
                "as_of_date": "2026-07-31",
                "constituents": [],
            },
            "etf_index_mapping": {
                "etf_id": "original-mapping",
                "index_id": "y",
                "effective_from": "2024-01-01",
            },
            "etf_holdings": {
                "etf_id": "original-holdings",
                "as_of_date": "2026-07-31",
                "holdings": [],
            },
        }
        adapter = SimpleNamespace(fetch_standardized_payload=mock.Mock(return_value=fake_payload))
        rebound_captured: list[Any] = []
        result = _fake_result()

        def capture_persist(payload: Any, uow_factory: Any) -> Any:
            rebound_captured.append(payload)
            return result

        with mock.patch.object(cli, "persist_exposure", side_effect=capture_persist):
            stdout = io.StringIO()
            rc = cli.run(
                etf_id=_FAKE_ETF_ID,
                fixture_path=None,
                adapter=adapter,  # type: ignore[arg-type]
                uow_factory=mock.Mock(),
                stdout=stdout,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(len(rebound_captured), 1)
        rebound = rebound_captured[0]
        self.assertEqual(
            rebound["etf_index_mapping"]["etf_id"],
            str(_FAKE_ETF_ID),
        )
        self.assertEqual(
            rebound["etf_holdings"]["etf_id"],
            str(_FAKE_ETF_ID),
        )

    def test_success_output_is_one_json_line(self) -> None:
        fake_payload = {
            "provider_key": "akshare",
            "dataset_key": "exposure_bundle",
            "observed_at": "2026-07-31T12:00:00+00:00",
            "index_profile": {
                "index_code": "000300",
                "index_name": "CSI 300",
                "category": "Broad Market",
            },
            "index_constituents": {
                "index_code": "000300",
                "as_of_date": "2026-07-31",
                "constituents": [],
            },
            "etf_index_mapping": {"etf_id": "x", "index_id": "y", "effective_from": "2024-01-01"},
            "etf_holdings": {"etf_id": "x", "as_of_date": "2026-07-31", "holdings": []},
        }
        adapter = SimpleNamespace(fetch_standardized_payload=mock.Mock(return_value=fake_payload))
        result = _fake_result()
        with mock.patch.object(cli, "persist_exposure", return_value=result):
            stdout = io.StringIO()
            rc = cli.run(
                etf_id=_FAKE_ETF_ID,
                fixture_path=None,
                adapter=adapter,  # type: ignore[arg-type]
                uow_factory=mock.Mock(),
                stdout=stdout,
            )

        self.assertEqual(rc, 0)
        lines = stdout.getvalue().strip().split("\n")
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertIn("index_id", parsed)

    def test_adapter_error_raises_from_run(self) -> None:
        adapter = SimpleNamespace(
            fetch_standardized_payload=mock.Mock(
                side_effect=RealProviderRequiresExplicitEnablementError("disabled")
            )
        )
        stdout = io.StringIO()
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            cli.run(
                etf_id=_FAKE_ETF_ID,
                fixture_path=None,
                adapter=adapter,  # type: ignore[arg-type]
                uow_factory=mock.Mock(),
                stdout=stdout,
            )

    def test_instrument_not_found_error_propagates(self) -> None:
        fake_payload = {
            "provider_key": "akshare",
            "dataset_key": "exposure_bundle",
            "observed_at": "2026-07-31T12:00:00+00:00",
            "index_profile": {
                "index_code": "000300",
                "index_name": "CSI 300",
                "category": "Broad Market",
            },
            "index_constituents": {
                "index_code": "000300",
                "as_of_date": "2026-07-31",
                "constituents": [],
            },
            "etf_index_mapping": {"etf_id": "x", "index_id": "y", "effective_from": "2024-01-01"},
            "etf_holdings": {"etf_id": "x", "as_of_date": "2026-07-31", "holdings": []},
        }
        adapter = SimpleNamespace(fetch_standardized_payload=mock.Mock(return_value=fake_payload))
        persist_error = InstrumentNotFoundError("etf not found")

        with (
            mock.patch.object(cli, "persist_exposure", side_effect=persist_error),
            self.assertRaises(InstrumentNotFoundError) as ctx,
        ):
            cli.run(
                etf_id=_FAKE_ETF_ID,
                fixture_path=None,
                adapter=adapter,  # type: ignore[arg-type]
                uow_factory=mock.Mock(),
                stdout=io.StringIO(),
            )
        self.assertIn("etf not found", str(ctx.exception))


class InvalidUuidPreventsAdapterUowTest(unittest.TestCase):
    """Invalid UUID must exit before adapter / UoW factory are accessed."""

    def test_invalid_uuid_does_not_touch_adapter(self) -> None:
        adapter = mock.Mock()
        uow_factory = mock.Mock()
        stderr = io.StringIO()

        with mock.patch("sys.stderr", stderr):
            rc = cli.main(["--etf-id", "not-a-uuid", "--fixture-path", "/tmp/nonexistent.json"])

        self.assertEqual(rc, 2)
        stderr_val = stderr.getvalue()
        self.assertTrue(stderr_val.startswith("error: "))
        self.assertEqual(stderr_val.count("\n"), 1)
        self.assertIn("invalid UUID", stderr_val)
        adapter.fetch_standardized_payload.assert_not_called()
        uow_factory.assert_not_called()


class MainProductionWiringTest(unittest.TestCase):
    """Production ``main`` path with engine creation and disposal."""

    def test_engine_disposed_on_success(self) -> None:
        engine = mock.Mock()

        with (
            mock.patch(
                "invest_pipeline.exposure_cli.create_engine",
                return_value=engine,
            ),
            mock.patch.object(cli, "run", return_value=0),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            rc = cli.main(["--etf-id", str(_FAKE_ETF_ID), "--fixture-path", "/tmp/foo.json"])

        self.assertEqual(rc, 0)
        engine.dispose.assert_called_once()

    def test_engine_disposed_on_error(self) -> None:
        engine = mock.Mock()

        with (
            mock.patch(
                "invest_pipeline.exposure_cli.create_engine",
                return_value=engine,
            ),
            mock.patch.object(cli, "run", side_effect=RuntimeError("boom")),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            cli.main(["--etf-id", str(_FAKE_ETF_ID), "--fixture-path", "/tmp/foo.json"])

        engine.dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
