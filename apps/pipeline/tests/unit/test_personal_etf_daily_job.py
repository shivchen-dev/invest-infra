"""Focused unit tests for the ``personal_etf_daily_job`` Dagster asset job.

Covers graph registration / ordering, the AkShare enrichment runtime
branches (non-Cifang skip, disabled fail-closed, partial/failed raw
rejection with no upsert, success) and the UTC-based partition
contract.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import dagster as dg
from invest_pipeline.assets import (
    _ETF_INPUT_SNAPSHOT_PARTITIONS,
    _STOCK_MARKET_DATA_PARTITIONS,
    EtfAkshareEnrichmentUnavailableError,
    etf_akshare_daily_bars,
    etf_daily_bars,
    etf_daily_bars_raw,
    etf_input_snapshot,
    etf_instruments,
    etf_instruments_raw,
    personal_candidate_pool,
    seed_instruments,
)
from invest_pipeline.config import Settings
from invest_pipeline.definitions import defs, personal_etf_daily_job

_PARTITION_KEY = "2026-07-31"

_EXPECTED_SELECTION: tuple[dg.AssetsDefinition, ...] = (
    etf_instruments_raw,
    etf_instruments,
    etf_daily_bars_raw,
    etf_daily_bars,
    etf_akshare_daily_bars,
    etf_input_snapshot,
    personal_candidate_pool,
)


@contextmanager
def _patch_enrichment_assets(
    *,
    provider_key: str,
    enabled: bool,
    write_raw: MagicMock,
    upsert: MagicMock,
    symbols: tuple[str, ...] = (),
) -> Iterator[tuple[MagicMock, MagicMock, MagicMock]]:
    """Patch the enrichment asset's outbound dependencies.

    Yields ``(engine, akshare_provider, akshare_settings_factory)``
    so each test can assert on the relevant mocks. The helper applies
    the eight patches shared by every runtime branch; per-test
    variations live in the ``write_raw`` / ``upsert`` mocks and the
    ``symbols`` tuple.
    """
    from invest_pipeline import assets

    engine = MagicMock(name="Engine")
    akshare_settings = MagicMock(name="AkshareSettings")
    akshare_settings.enabled = enabled
    akshare_provider = MagicMock(name="AkshareInstrumentProvider")
    load_universe = MagicMock(name="load_personal_universe")
    load_universe.return_value.symbols = symbols
    akshare_settings_factory = MagicMock(
        name="AkshareSettings", return_value=akshare_settings
    )
    with (
        patch.object(
            assets, "get_settings", return_value=Settings(provider_key=provider_key)
        ),
        patch.object(assets, "build_engine", return_value=engine),
        patch.object(assets, "session_factory", return_value=MagicMock()),
        patch.object(assets, "AkshareSettings", akshare_settings_factory),
        patch.object(assets, "AkshareInstrumentProvider", akshare_provider),
        patch.object(assets, "write_etf_daily_bars_raw", write_raw),
        patch.object(assets, "upsert_etf_daily_bars", upsert),
        patch.object(assets, "load_personal_universe", load_universe),
    ):
        yield engine, akshare_provider, akshare_settings_factory


def _invoke_enrichment(partition_key: str = _PARTITION_KEY):
    return etf_akshare_daily_bars.op.compute_fn.decorated_fn(
        dg.build_asset_context(partition_key=partition_key)
    )


def _invoke_daily_asset(asset, partition_key: str = _PARTITION_KEY):
    return asset.op.compute_fn.decorated_fn(
        dg.build_asset_context(partition_key=partition_key)
    )


@contextmanager
def _patch_daily_assets(
    *,
    provider_key: str,
    baostock_enabled: bool,
    raw_result=None,
    primary_request=None,
    primary_attempts=(),
    fallback_request=None,
):
    from invest_pipeline import assets

    provider = MagicMock(provider_key=provider_key)
    fallback_provider = MagicMock(provider_key="baostock")
    engine = MagicMock(name="Engine")
    factory = MagicMock(name="session_factory")
    settings = Settings(provider_key=provider_key)
    settings.personal_universe_path = MagicMock()
    universe = SimpleNamespace(symbols=("510300", "159915"))
    requests = MagicMock()

    def _request_lookup(*, provider_key, dataset_key, request_key):
        assert dataset_key == "etf_daily_bars"
        assert request_key == "daily-bars-2026-07-31-2026-07-31-510300-159915"
        return fallback_request if provider_key == "baostock" else primary_request

    requests.get_by_logical_key.side_effect = _request_lookup
    attempts = MagicMock()
    attempts.list_by_request.return_value = list(primary_attempts)
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.provider_requests = requests
    uow.provider_attempts = attempts
    uow_factory = MagicMock(return_value=uow)
    baostock_settings = SimpleNamespace(enabled=baostock_enabled)

    with (
        patch.object(assets, "get_settings", return_value=settings),
        patch.object(assets, "build_provider", return_value=provider),
        patch.object(assets, "build_engine", return_value=engine),
        patch.object(assets, "session_factory", return_value=factory),
        patch.object(assets, "load_personal_universe", return_value=universe),
        patch.object(assets, "BaostockSettings", return_value=baostock_settings),
        patch.object(
            assets, "BaostockEtfDailyBarsAdapter", return_value=fallback_provider
        ) as adapter,
        patch.object(
            assets,
            "write_etf_daily_bars_raw_with_fallback",
            return_value=raw_result,
        ) as write_with_fallback,
        patch.object(
            assets, "write_etf_daily_bars_raw", return_value=raw_result
        ) as write_raw,
        patch.object(assets, "upsert_etf_daily_bars") as upsert,
        patch("invest_storage.SqlAlchemyUnitOfWork", uow_factory),
    ):
        yield SimpleNamespace(
            provider=provider,
            fallback_provider=fallback_provider,
            engine=engine,
            adapter=adapter,
            write=write_with_fallback,
            write_raw=write_raw,
            upsert=upsert,
            attempts=attempts,
        )


class EtfDailyBarsBaostockFallbackTest(unittest.TestCase):
    def _raw_result(self, **overrides):
        from invest_pipeline.etf_daily_bars import RawEtlResult

        values = dict(
            request_id=MagicMock(),
            attempt_id=MagicMock(),
            batch_id=MagicMock(),
            request_status="succeeded",
            attempt_status="succeeded",
            record_count=2,
            provider_key="akshare",
        )
        values.update(overrides)
        return RawEtlResult(**values)

    def test_raw_default_off_preserves_primary_and_actual_provider_metadata(self):
        result = self._raw_result(provider_key=None)
        with _patch_daily_assets(
            provider_key="akshare", baostock_enabled=False, raw_result=result
        ) as patched:
            materialized = _invoke_daily_asset(etf_daily_bars_raw)

        patched.adapter.assert_not_called()
        patched.write.assert_not_called()
        patched.write_raw.assert_called_once_with(
            patched.provider,
            patched.write_raw.call_args.args[1],
            symbols=["510300", "159915"],
            start_date=date(2026, 7, 31),
            end_date=date(2026, 7, 31),
            unit_of_work_factory=patched.write_raw.call_args.kwargs[
                "unit_of_work_factory"
            ],
        )
        self.assertEqual(materialized.metadata["provider"], "akshare")

    def test_raw_non_akshare_never_constructs_baostock(self):
        result = self._raw_result(provider_key="fixture_dev")
        with _patch_daily_assets(
            provider_key="fixture_dev", baostock_enabled=True, raw_result=result
        ) as patched:
            _invoke_daily_asset(etf_daily_bars_raw)

        patched.adapter.assert_not_called()
        patched.write.assert_not_called()
        patched.write_raw.assert_called_once()

    def test_raw_transient_fallback_forwards_exact_symbols_dates_and_winner(self):
        result = self._raw_result(provider_key="baostock")
        with _patch_daily_assets(
            provider_key="akshare", baostock_enabled=True, raw_result=result
        ) as patched:
            materialized = _invoke_daily_asset(etf_daily_bars_raw)

        patched.adapter.assert_called_once()
        self.assertIs(
            patched.write.call_args.kwargs["fallback_provider"],
            patched.fallback_provider,
        )
        self.assertTrue(patched.write.call_args.kwargs["fallback_enabled"])
        self.assertEqual(patched.write.call_args.kwargs["symbols"], ["510300", "159915"])
        self.assertEqual(patched.write.call_args.kwargs["start_date"], date(2026, 7, 31))
        self.assertEqual(patched.write.call_args.kwargs["end_date"], date(2026, 7, 31))
        self.assertEqual(materialized.metadata["provider"], "baostock")

    def test_downstream_primary_success_wins_over_existing_fallback(self):
        primary = SimpleNamespace(id="primary", status="succeeded")
        fallback = SimpleNamespace(id="fallback", status="succeeded")
        with _patch_daily_assets(
            provider_key="akshare",
            baostock_enabled=True,
            primary_request=primary,
            fallback_request=fallback,
        ) as patched:
            patched.upsert.return_value = SimpleNamespace(inserted=2, skipped=0, total=2)
            materialized = _invoke_daily_asset(etf_daily_bars)

        self.assertEqual(patched.upsert.call_args.kwargs["provider_key"], "akshare")
        self.assertEqual(materialized.metadata["provider"], "akshare")
        patched.attempts.list_by_request.assert_not_called()

    def test_downstream_transient_latest_failure_selects_successful_fallback(self):
        primary = SimpleNamespace(id="primary", status="failed")
        fallback = SimpleNamespace(id="fallback", status="succeeded")
        attempts = (
            SimpleNamespace(attempt_no=1, status="failed", error_code="BadResponse"),
            SimpleNamespace(
                attempt_no=2,
                status="failed",
                error_code="ProviderTimeoutError",
            ),
        )
        with _patch_daily_assets(
            provider_key="akshare",
            baostock_enabled=True,
            primary_request=primary,
            primary_attempts=attempts,
            fallback_request=fallback,
        ) as patched:
            patched.upsert.return_value = SimpleNamespace(inserted=2, skipped=0, total=2)
            materialized = _invoke_daily_asset(etf_daily_bars)

        self.assertEqual(patched.upsert.call_args.kwargs["provider_key"], "baostock")
        self.assertEqual(materialized.metadata["provider"], "baostock")

    def test_downstream_fails_closed_for_disabled_nontransient_partial_failed_or_missing(self):
        cases = (
            (False, "ProviderTimeoutError", SimpleNamespace(id="f", status="succeeded")),
            (True, "ProviderAuthenticationError", SimpleNamespace(id="f", status="succeeded")),
            (True, "ProviderTimeoutError", SimpleNamespace(id="f", status="partial")),
            (True, "ProviderTimeoutError", SimpleNamespace(id="f", status="failed")),
            (True, "ProviderUnavailableError", None),
        )
        for enabled, error_code, fallback in cases:
            with self.subTest(enabled=enabled, error_code=error_code, fallback=fallback):
                primary = SimpleNamespace(id="primary", status="failed")
                attempts = (
                    SimpleNamespace(
                        attempt_no=1, status="failed", error_code=error_code
                    ),
                )
                with _patch_daily_assets(
                    provider_key="akshare",
                    baostock_enabled=enabled,
                    primary_request=primary,
                    primary_attempts=attempts,
                    fallback_request=fallback,
                ) as patched:
                    result = _invoke_daily_asset(etf_daily_bars)
                patched.upsert.assert_not_called()
                self.assertTrue(result.metadata["skipped_asset"])

    def test_later_nontransient_primary_failure_rejects_stale_fallback_success(self):
        primary = SimpleNamespace(id="primary", status="failed")
        fallback = SimpleNamespace(id="fallback", status="succeeded")
        attempts = (
            SimpleNamespace(
                attempt_no=1, status="failed", error_code="ProviderTimeoutError"
            ),
            SimpleNamespace(
                attempt_no=2, status="failed", error_code="ProviderRateLimitError"
            ),
        )
        with _patch_daily_assets(
            provider_key="akshare",
            baostock_enabled=True,
            primary_request=primary,
            primary_attempts=attempts,
            fallback_request=fallback,
        ) as patched:
            result = _invoke_daily_asset(etf_daily_bars)

        patched.upsert.assert_not_called()
        self.assertTrue(result.metadata["skipped_asset"])


class PersonalEtfDailyJobRegistrationTest(unittest.TestCase):
    def test_module_exposes_job_with_expected_name(self) -> None:
        self.assertEqual(personal_etf_daily_job.name, "personal_etf_daily_job")

    def test_definitions_resolves_job_under_expected_name(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertIsInstance(job_def, dg.JobDefinition)
        self.assertEqual(job_def.name, "personal_etf_daily_job")
        self.assertTrue(
            job_def.is_asset_job,
            "personal_etf_daily_job must materialise assets, not ops",
        )


class PersonalEtfDailyJobSelectionTest(unittest.TestCase):
    def test_selection_is_exactly_the_seven_etf_and_pool_assets(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        selected_keys = set(job_def.asset_layer.selected_asset_keys)
        expected_keys = {asset.key for asset in _EXPECTED_SELECTION}
        self.assertEqual(selected_keys, expected_keys)

    def test_selection_includes_akshare_enrichment_asset(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertIn(
            etf_akshare_daily_bars.key,
            job_def.asset_layer.selected_asset_keys,
        )

    def test_selection_excludes_seed_instruments(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertNotIn(
            seed_instruments.key,
            job_def.asset_layer.selected_asset_keys,
        )

    def test_selection_has_no_extra_or_missing_assets(self) -> None:
        job_def = defs.resolve_job_def("personal_etf_daily_job")
        self.assertEqual(
            len(job_def.asset_layer.selected_asset_keys),
            len(_EXPECTED_SELECTION),
        )


class PersonalCandidatePoolDependencyOrderingTest(unittest.TestCase):
    """Pin the corrected graph: bars -> enrichment -> snapshot -> pool."""

    def test_personal_candidate_pool_depends_on_akshare_enrichment(self) -> None:
        dependency_keys = personal_candidate_pool.dependency_keys
        self.assertIn(
            dg.AssetKey("etf_akshare_daily_bars"),
            dependency_keys,
            "personal_candidate_pool must depend on etf_akshare_daily_bars "
            "so the enrichment runs before candidate-pool publication",
        )

    def test_personal_candidate_pool_still_depends_on_etf_daily_bars(self) -> None:
        dependency_keys = personal_candidate_pool.dependency_keys
        self.assertIn(dg.AssetKey("etf_daily_bars"), dependency_keys)
        self.assertIn(dg.AssetKey("etf_input_snapshot"), dependency_keys)

    def test_akshare_enrichment_depends_on_cifang_daily_bars(self) -> None:
        dependency_keys = etf_akshare_daily_bars.dependency_keys
        self.assertIn(dg.AssetKey("etf_daily_bars"), dependency_keys)

    def test_etf_input_snapshot_depends_on_akshare_enrichment(self) -> None:
        # Without this edge the snapshot could capture pre-enrichment bars
        # on the Cifang path, the exact regression found by real-provider
        # acceptance.
        dependency_keys = etf_input_snapshot.dependency_keys
        self.assertIn(
            dg.AssetKey("etf_akshare_daily_bars"),
            dependency_keys,
            "etf_input_snapshot must depend on etf_akshare_daily_bars "
            "so the AkShare enrichment lands before the snapshot "
            "captures core.daily_bars",
        )


class PersonalEtfDailyJobEndOffsetTest(unittest.TestCase):
    def test_etf_end_offset_one_stock_end_offset_zero_today_usable(self) -> None:
        # UTC-based lookup keeps the partition contract stable across
        # the Asia/Shanghai midnight boundary.
        today = datetime.now(UTC).date().isoformat()
        self.assertEqual(_ETF_INPUT_SNAPSHOT_PARTITIONS.end_offset, 1)
        self.assertEqual(_STOCK_MARKET_DATA_PARTITIONS.end_offset, 0)
        self.assertTrue(_ETF_INPUT_SNAPSHOT_PARTITIONS.has_partition_key(today))


class EtfAkshareEnrichmentAssetPartitionsTest(unittest.TestCase):
    def test_enrichment_asset_uses_etf_daily_partitions(self) -> None:
        self.assertIsInstance(
            etf_akshare_daily_bars.partitions_def,
            dg.DailyPartitionsDefinition,
        )
        self.assertIs(
            etf_akshare_daily_bars.partitions_def,
            etf_daily_bars.partitions_def,
        )


class EtfAkshareEnrichmentAssetSkippedTest(unittest.TestCase):
    """Non-Cifang primary path: skipped, no network or DB work."""

    def test_non_cifang_returns_skipped_without_network_or_db_work(self) -> None:
        write_raw = MagicMock(name="write_etf_daily_bars_raw")
        upsert = MagicMock(name="upsert_etf_daily_bars")
        with _patch_enrichment_assets(
            provider_key="fixture_dev",
            enabled=False,
            write_raw=write_raw,
            upsert=upsert,
        ) as (engine, akshare_provider, akshare_settings_factory):
            result = _invoke_enrichment()

        self.assertTrue(result.metadata["skipped"])
        self.assertEqual(result.metadata["provider"], "fixture_dev")
        self.assertIn("fixture_dev", result.metadata["reason"])
        self.assertEqual(result.metadata["partition_key"], _PARTITION_KEY)
        akshare_settings_factory.assert_not_called()
        akshare_provider.assert_not_called()
        write_raw.assert_not_called()
        upsert.assert_not_called()
        engine.dispose.assert_not_called()


class EtfAkshareEnrichmentAssetDisabledTest(unittest.TestCase):
    """Cifang primary with AkShare disabled: fail-closed raise."""

    def test_akshare_disabled_raises_without_writing_raw_or_upsert(self) -> None:
        write_raw = MagicMock(name="write_etf_daily_bars_raw")
        upsert = MagicMock(name="upsert_etf_daily_bars")
        with _patch_enrichment_assets(
            provider_key="cifangquant",
            enabled=False,
            write_raw=write_raw,
            upsert=upsert,
        ) as (engine, akshare_provider, _factory):
            with self.assertRaises(EtfAkshareEnrichmentUnavailableError) as ctx:
                _invoke_enrichment()

        message = str(ctx.exception)
        self.assertIn("akshare", message.lower())
        self.assertIn("enabled", message.lower())
        akshare_provider.assert_not_called()
        write_raw.assert_not_called()
        upsert.assert_not_called()
        engine.dispose.assert_not_called()


class EtfAkshareEnrichmentAssetRawFetchFailedTest(unittest.TestCase):
    """Unsuccessful AkShare raw fetch: fail-closed and no upsert."""

    def test_failed_raw_fetch_raises_and_skips_upsert(self) -> None:
        from invest_pipeline.etf_daily_bars import RawEtlResult

        failed_result = RawEtlResult(
            request_id=MagicMock(name="request_id"),
            attempt_id=MagicMock(name="attempt_id"),
            batch_id=None,
            request_status="failed",
            attempt_status="failed",
            record_count=0,
        )
        write_raw = MagicMock(
            name="write_etf_daily_bars_raw", return_value=failed_result
        )
        upsert = MagicMock(name="upsert_etf_daily_bars")

        with _patch_enrichment_assets(
            provider_key="cifangquant",
            enabled=True,
            write_raw=write_raw,
            upsert=upsert,
            symbols=("510300",),
        ) as (engine, _provider, _factory):
            with self.assertRaises(EtfAkshareEnrichmentUnavailableError) as ctx:
                _invoke_enrichment()

        message = str(ctx.exception)
        self.assertIn("not fully successful", message)
        self.assertIn(_PARTITION_KEY, message)
        write_raw.assert_called_once()
        upsert.assert_not_called()
        engine.dispose.assert_called_once_with()

    def test_partial_raw_fetch_raises_and_skips_upsert(self) -> None:
        """``batch_id is None`` (partial success) is also fail-closed."""

        from invest_pipeline.etf_daily_bars import RawEtlResult

        partial_result = RawEtlResult(
            request_id=MagicMock(name="request_id"),
            attempt_id=MagicMock(name="attempt_id"),
            batch_id=MagicMock(name="partial_batch_id"),
            request_status="partial",
            attempt_status="succeeded",
            record_count=0,
        )
        write_raw = MagicMock(
            name="write_etf_daily_bars_raw", return_value=partial_result
        )
        upsert = MagicMock(name="upsert_etf_daily_bars")

        with _patch_enrichment_assets(
            provider_key="cifangquant",
            enabled=True,
            write_raw=write_raw,
            upsert=upsert,
            symbols=("510300",),
        ) as (engine, _provider, _factory):
            with self.assertRaises(EtfAkshareEnrichmentUnavailableError):
                _invoke_enrichment()

        upsert.assert_not_called()
        engine.dispose.assert_called_once_with()


class EtfAkshareEnrichmentAssetSuccessTest(unittest.TestCase):
    """Successful raw fetch: upsert with ``provider_key="akshare"``."""

    def test_successful_raw_fetch_upserts_with_provider_key_akshare(self) -> None:
        from invest_pipeline.etf_daily_bars import RawEtlResult, UpsertSummary

        request_id = MagicMock(name="request_id")
        attempt_id = MagicMock(name="attempt_id")
        batch_id = MagicMock(name="batch_id")
        successful_result = RawEtlResult(
            request_id=request_id,
            attempt_id=attempt_id,
            batch_id=batch_id,
            request_status="succeeded",
            attempt_status="succeeded",
            record_count=2,
        )
        write_raw = MagicMock(
            name="write_etf_daily_bars_raw", return_value=successful_result
        )
        summary = UpsertSummary(inserted=2, skipped=0)
        upsert = MagicMock(name="upsert_etf_daily_bars", return_value=summary)

        captured: dict[str, object] = {}

        def _capture(*args: object, **kwargs: object) -> object:
            captured["args"] = args
            captured.update(kwargs)
            return summary

        upsert.side_effect = _capture

        with _patch_enrichment_assets(
            provider_key="cifangquant",
            enabled=True,
            write_raw=write_raw,
            upsert=upsert,
            symbols=("510300", "510500"),
        ) as (engine, _provider, _factory):
            result = _invoke_enrichment()

        upsert.assert_called_once()
        self.assertEqual(captured["provider_key"], "akshare")
        self.assertEqual(captured["dataset_key"], "etf_daily_bars")
        self.assertEqual(
            captured["request_key"], "daily-bars-2026-07-31-2026-07-31-510300-510500"
        )
        self.assertFalse(result.metadata["skipped"])
        self.assertEqual(result.metadata["provider"], "akshare")
        self.assertEqual(result.metadata["inserted"], 2)
        self.assertEqual(result.metadata["total"], 2)
        self.assertEqual(
            result.metadata["request_key"],
            "daily-bars-2026-07-31-2026-07-31-510300-510500",
        )
        self.assertEqual(result.metadata["partition_key"], _PARTITION_KEY)
        engine.dispose.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
